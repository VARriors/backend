from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

from app.db import init_mongo

load_dotenv()

mongo_client, db = init_mongo()

def create_app():
    app = Flask(__name__)
    CORS(app)

    from app.routes.candidates import candidates_bp
    from app.routes.candidate_questionnaire import candidate_questionnaire_bp
    from app.routes.employers import employers_bp
    from app.routes.jobs_api import jobs_api_bp
    from app.routes.matching import matching_bp
    from app.routes.candidate_api import candidate_api_bp

    app.register_blueprint(candidates_bp, url_prefix='/api/candidates')
    app.register_blueprint(candidate_questionnaire_bp, url_prefix='/api/candidates')
    app.register_blueprint(employers_bp, url_prefix='/api/employers')
    app.register_blueprint(jobs_api_bp, url_prefix='/api')
    app.register_blueprint(matching_bp, url_prefix='/api/matching')
    app.register_blueprint(candidate_api_bp, url_prefix='/api/candidate')

    @app.route('/', methods=['GET'])
    def index():
        return {"message": "Mega duży ważny błąd: API działa, ale to tylko testowy endpoint!"}

    @app.route('/health', methods=['GET'])
    def health_check():
        try:
            mongo_client.admin.command("ping")
            database_status = "ok"
        except Exception:
            database_status = "error"

        return {
            "status": "ok" if database_status == "ok" else "degraded",
            "message": "mMurząd pracy API is running!",
            "database": database_status,
        }

    return app
