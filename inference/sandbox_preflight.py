"""Fail before evaluation if a configured Python executor cannot run code."""
from sandbox_fusion import RunCodeRequest, run_code


def check_sandbox_endpoints(endpoints):
    if not endpoints:
        raise RuntimeError('Python tool is enabled but no sandbox endpoint is configured')
    for endpoint in endpoints:
        try:
            result = run_code(RunCodeRequest(code='print(17 * 19)', language='python', run_timeout=10),
                              endpoint=endpoint, max_attempts=1, client_timeout=30)
            run = result.run_result
            if run is None or run.return_code != 0 or (run.stdout or '').strip() != '323':
                raise RuntimeError('unexpected sandbox execution result')
        except Exception as exc:
            raise RuntimeError(f'Python sandbox preflight failed for {endpoint}: {type(exc).__name__}') from exc
