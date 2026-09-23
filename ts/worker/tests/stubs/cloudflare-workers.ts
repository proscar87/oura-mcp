export class DurableObject<E = unknown> {
  constructor(protected ctx: any, protected env: E) {}
}
