export class GatewayRequestError extends Error {
  readonly status = 400;
  readonly type = "invalid_request_error";

  constructor(message: string) {
    super(message);
    this.name = "GatewayRequestError";
  }
}

export class GatewayAuthError extends Error {
  readonly status = 502;
  readonly type = "authentication_error";

  constructor(message: string) {
    super(message);
    this.name = "GatewayAuthError";
  }
}

export class UpstreamError extends Error {
  readonly status: number;
  readonly type = "upstream_error";

  constructor(message: string, status: number) {
    super(message);
    this.name = "UpstreamError";
    this.status = status;
  }
}
