"""Pruebas del almacenamiento y la rotación de credenciales de OAuth2.

NO TOCAN LA RED. El endpoint de token se sustituye por uno falso.

Lo que se prueba aquí no es «guardar un JSON»: es que la ventana en la que el
refresh token viejo ya murió y el nuevo todavía no está guardado sea lo más
corta posible, y que nunca quede un archivo a medio escribir. Oura invalida el
refresh token en cuanto se canjea; equivocarse aquí deja al usuario fuera de su
propia cuenta hasta que vuelva a autorizar desde el navegador.
"""

import json
import os
import stat
import time

import pytest

from oura_mcp import credenciales as cr
from oura_mcp.cliente import ErrorOura, Secreto


@pytest.fixture(autouse=True)
def _aislar(tmp_path, monkeypatch):
    """Cada prueba con su propio archivo, y sin tocar el llavero de nadie."""
    monkeypatch.setenv("OURA_CREDENCIALES", str(tmp_path / "cred.json"))
    monkeypatch.setenv("OURA_SIN_LLAVERO", "1")
    return tmp_path


def _cred(refresco="R1", expira_en=None, alcances=("daily",)):
    return cr.Credenciales(
        acceso=Secreto("A1"),
        refresco=Secreto(refresco) if refresco else None,
        expira_en=time.time() + 3600 if expira_en is None else expira_en,
        alcances=alcances,
    )


# ── Guardar ─────────────────────────────────────────────────────────────────
def test_el_archivo_queda_en_600():
    ruta = cr.guardar(_cred())
    modo = stat.S_IMODE(os.stat(ruta).st_mode)
    assert modo == 0o600, oct(modo)


def test_el_directorio_queda_en_700(_aislar, monkeypatch):
    monkeypatch.setenv("OURA_CREDENCIALES", str(_aislar / "hondo" / "cred.json"))
    ruta = cr.guardar(_cred())
    modo = stat.S_IMODE(os.stat(os.path.dirname(ruta)).st_mode)
    assert modo == 0o700, oct(modo)


def test_ida_y_vuelta():
    cr.guardar(_cred(alcances=("daily", "heartrate")))
    leida = cr.cargar()
    assert leida.acceso.revelar() == "A1"
    assert leida.refresco.revelar() == "R1"
    assert leida.alcances == ("daily", "heartrate")


def test_sin_archivo_no_hay_credenciales():
    assert cr.cargar() is None


def test_un_archivo_corrupto_dice_qué_hacer(_aislar):
    ruta = _aislar / "cred.json"
    ruta.write_text("{no es json")
    with pytest.raises(ErrorOura, match="vuelve a autorizar"):
        cr.cargar()


def test_no_queda_basura_si_falla_a_medio_escribir(_aislar, monkeypatch):
    """Un archivo de credenciales a medio escribir es peor que ninguno: el
    refresh token viejo ya se consumió y el nuevo era lo único que salvaba la
    sesión."""
    def revienta(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(cr.os, "replace", revienta)
    with pytest.raises(OSError):
        cr.guardar(_cred())
    sobras = [p for p in os.listdir(_aislar) if p.startswith(".cred-")]
    assert sobras == [], sobras


def test_olvidar_no_falla_si_no_habia():
    cr.olvidar()          # sin excepción
    cr.guardar(_cred())
    cr.olvidar()
    assert cr.cargar() is None


# ── Que nada imprima los tokens ─────────────────────────────────────────────
def test_el_repr_de_las_credenciales_no_lleva_tokens():
    """`Secreto` se protege solo, pero un dataclass con repr automático los
    imprimiría por su cuenta."""
    c = _cred()
    assert "A1" not in repr(c)
    assert "R1" not in repr(c)
    assert "vigente" in repr(c)


def test_el_archivo_guardado_no_es_legible_por_otros(_aislar):
    """Obvio y por eso vale probarlo: el contenido SÍ lleva los tokens en claro,
    y lo único que los protege son los permisos."""
    ruta = cr.guardar(_cred())
    assert "R1" in open(ruta).read()
    assert stat.S_IMODE(os.stat(ruta).st_mode) & 0o077 == 0


# ── Caducidad ───────────────────────────────────────────────────────────────
def test_un_token_que_expira_en_tres_segundos_ya_esta_caducado():
    """La petición que se lance con él llegará tarde."""
    assert _cred(expira_en=time.time() + 3).caducado()
    assert not _cred(expira_en=time.time() + 3600).caducado()


# ── La rotación: donde se pierde la sesión si se hace mal ───────────────────
def _oura_de_tokens(monkeypatch, respuesta, registrar=None):
    def postear(datos):
        if registrar is not None:
            registrar.append(datos)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    monkeypatch.setattr(cr, "_postear", postear)


def test_refrescar_guarda_antes_de_devolver(monkeypatch):
    """LA LÍNEA QUE IMPORTA. Oura invalida el refresh token en cuanto se canjea;
    entre la respuesta y el guardado hay una ventana en la que el viejo ya murió
    y el nuevo no existe en disco. Esta prueba fija que sea lo más corta
    posible: al momento de devolver, ya está guardado."""
    _oura_de_tokens(monkeypatch, {"access_token": "A2", "refresh_token": "R2",
                                  "expires_in": 3600, "scope": "daily"})
    devuelta = cr.refrescar(_cred(), "id", "secreto")
    en_disco = cr.cargar()
    assert devuelta.refresco.revelar() == "R2"
    assert en_disco.refresco.revelar() == "R2"      # ya estaba guardado


def test_el_refresco_manda_el_token_viejo(monkeypatch):
    enviados = []
    _oura_de_tokens(monkeypatch, {"access_token": "A2", "refresh_token": "R2",
                                  "expires_in": 3600}, registrar=enviados)
    cr.refrescar(_cred(refresco="R1"), "id", "secreto")
    assert enviados[0]["grant_type"] == "refresh_token"
    assert enviados[0]["refresh_token"] == "R1"


def test_si_otro_proceso_ya_refresco_la_sesion_no_se_da_por_perdida(monkeypatch):
    """Dos herramientas MCP llamadas en paralelo es un caso real. El que pierde
    la carrera ve un 400 aunque la sesión esté viva, ya renovada por el otro."""
    cr.guardar(cr.Credenciales(acceso=Secreto("A9"), refresco=Secreto("R9"),
                               expira_en=time.time() + 3600, alcances=("daily",)))
    _oura_de_tokens(monkeypatch, ErrorOura("Oura rechazó el canje (400)"))
    recuperada = cr.refrescar(_cred(refresco="R1"), "id", "secreto")
    assert recuperada.acceso.revelar() == "A9"


def test_si_falla_y_no_hay_nada_guardado_se_propaga(monkeypatch):
    _oura_de_tokens(monkeypatch, ErrorOura("Oura rechazó el canje (400)"))
    with pytest.raises(ErrorOura, match="400"):
        cr.refrescar(_cred(), "id", "secreto")


def test_sin_refresh_token_se_dice_que_hay_que_autorizar(monkeypatch):
    with pytest.raises(ErrorOura, match="autorizar de nuevo"):
        cr.refrescar(_cred(refresco=None), "id", "secreto")


def test_se_guardan_los_alcances_concedidos_no_los_pedidos(monkeypatch):
    """La pantalla de consentimiento devuelve lo que el usuario ACEPTÓ, que no
    siempre es lo que se pidió. El autodiagnóstico se apoya en esto."""
    _oura_de_tokens(monkeypatch, {"access_token": "A2", "refresh_token": "R2",
                                  "expires_in": 3600, "scope": "daily personal"})
    nueva = cr.refrescar(_cred(alcances=("daily", "heartrate", "spo2")), "id", "s")
    assert nueva.alcances == ("daily", "personal")


def test_una_respuesta_sin_access_token_es_un_error(monkeypatch):
    _oura_de_tokens(monkeypatch, {"token_type": "Bearer"})
    with pytest.raises(ErrorOura, match="sin `access_token`"):
        cr.refrescar(_cred(), "id", "secreto")


def test_canjear_codigo_tambien_guarda(monkeypatch):
    enviados = []
    _oura_de_tokens(monkeypatch, {"access_token": "A1", "refresh_token": "R1",
                                  "expires_in": 3600}, registrar=enviados)
    cr.canjear_codigo("el-codigo", "id", "secreto")
    assert enviados[0]["grant_type"] == "authorization_code"
    assert enviados[0]["code"] == "el-codigo"
    assert cr.cargar().acceso.revelar() == "A1"


def test_el_redirect_por_defecto_lleva_diagonal_final():
    """No es estilo: el portal de Oura rechaza `…/callback` con
    `invalid_redirect_uri` y acepta `…/callback/`."""
    assert cr.REDIRECT_POR_DEFECTO.endswith("/callback/")
