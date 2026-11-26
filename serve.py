"""Run the application with Waitress rather than Flask's development server."""
import argparse
import os
from waitress import serve
from app import app

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    print(f'Simbanai Brahmans: http://{args.host}:{args.port}', flush=True)
    proxy = os.getenv('TRUSTED_PROXY')
    options = {}
    if proxy:
        if proxy == '*':
            parser.error('TRUSTED_PROXY must be one explicit proxy address, never a wildcard.')
        options = dict(trusted_proxy=proxy, trusted_proxy_count=1,
                       trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-host', 'x-forwarded-proto'})
    serve(app, host=args.host, port=args.port, **options)
