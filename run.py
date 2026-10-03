import logging

from waitress import serve

from app import create_app

app = create_app()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(f"LOL Data: http://{app.config['HOST']}:{app.config['PORT']}", flush=True)
    serve(app, host=app.config["HOST"], port=app.config["PORT"], threads=6)
