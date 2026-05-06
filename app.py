import os
import logging
from datetime import datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db = SQLAlchemy()
login_manager = LoginManager()

oauth = None
google = None
oauth_enabled = False


# ------------------- APP SETUP -------------------

def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///resume_parser.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    cors_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5000,https://jobsniffr.onrender.com"
    ).split(",")

    CORS(app, origins=cors_origins, supports_credentials=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login"

    configure_oauth(app)
    register_routes(app)

    with app.app_context():
        db.create_all()

    return app


# ------------------- OAUTH -------------------

def configure_oauth(app):
    global oauth, google, oauth_enabled

    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not google_client_id or not google_client_secret:
        return

    from authlib.integrations.flask_client import OAuth

    oauth = OAuth(app)

    google = oauth.register(
        name="google",
        client_id=google_client_id,
        client_secret=google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
            "prompt": "select_account",
        },
    )

    oauth_enabled = True


# ------------------- MODELS -------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True)
    name = db.Column(db.String(100))
    google_id = db.Column(db.String(120), unique=True)
    avatar_url = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ------------------- ROUTES -------------------

def register_routes(app):

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/login")
    def login():
        return render_template("login.html")

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    # -------- GOOGLE AUTH --------

    @app.route("/auth/google")
    def google_auth():
        redirect_uri = url_for("google_callback", _external=True)
        return google.authorize_redirect(redirect_uri)

    @app.route("/auth/google/callback")
    def google_callback():
        token = google.authorize_access_token()
        user_info = token.get("userinfo") or google.parse_id_token(token)

        google_id = user_info.get("sub")
        email = user_info.get("email")
        name = user_info.get("name")

        user = User.query.filter_by(google_id=google_id).first()

        if not user:
            user = User(email=email, name=name, google_id=google_id)
            db.session.add(user)

        db.session.commit()
        login_user(user)

        return redirect(url_for("dashboard"))

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect("/login")

    # -------- API --------

    @app.route("/api/test")
    def test():
        return jsonify({
            "success": True,
            "database_info": {
                "total_resumes": 0
            }
        })

    @app.route("/api/upload", methods=["POST"])
    @login_required
    def upload():
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file uploaded"}), 400

        file = request.files["file"]

        return jsonify({
            "success": True,
            "message": "File received",
            "filename": file.filename,
            "database_info": {
                "total_resumes": 1
            }
        })


# ------------------- RUN -------------------

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)