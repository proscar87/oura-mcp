export class DurableObject<E = unknown> {
  constructor(protected ctx: any, protected env: E) {}
}

/** Only so the OAuth provider's `instanceof` check has something to test against. */
export class WorkerEntrypoint<E = unknown> {
  constructor(protected ctx: any, protected env: E) {}
}
