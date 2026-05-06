import os
import json
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


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///resume_parser.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    cors_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5000,https://your-app.onrender.com"
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


def configure_oauth(app):
    global oauth, google, oauth_enabled

    google_client_id = os.getenv("GOOGLE_CLIENT_ID")
    google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not google_client_id or not google_client_secret:
        logger.warning("⚠️ Google OAuth not configured")
        return

    try:
        from authlib.integrations.flask_client import OAuth

        oauth = OAuth(app)

        google = oauth.register(
            name="google",
            client_id=google_client_id,
            client_secret=google_client_secret,
            access_token_url="https://oauth2.googleapis.com/token",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            api_base_url="https://www.googleapis.com/oauth2/v2/",
            client_kwargs={
                "scope": "openid email profile",
                "prompt": "select_account"
            },
        )

        oauth_enabled = True
        logger.info("✅ Google OAuth enabled")

    except Exception as e:
        logger.error(f"❌ OAuth setup failed: {e}")


# ------------------- MODELS -------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    avatar_url = db.Column(db.String(300))
    google_id = db.Column(db.String(120), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "avatar_url": self.avatar_url
        }


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
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    # ---------------- AUTH ----------------

    @app.route("/auth/google")
    def google_auth():
        if not google:
            return jsonify({"success": False, "error": "OAuth not configured"}), 400

        redirect_uri = url_for("google_callback", _external=True)
        return google.authorize_redirect(redirect_uri)

    @app.route("/auth/google/callback")
    def google_callback():
        if not google:
            return jsonify({"success": False, "error": "OAuth not configured"}), 400

        try:
            token = google.authorize_access_token()

            resp = google.get("userinfo")
            user_info = resp.json()

            user = User.query.filter_by(google_id=user_info["id"]).first()

            if not user:
                user = User(
                    email=user_info["email"],
                    name=user_info.get("name", user_info["email"]),
                    google_id=user_info["id"],
                    avatar_url=user_info.get("picture"),
                )
                db.session.add(user)
            else:
                user.name = user_info.get("name", user.name)
                user.avatar_url = user_info.get("picture")
                user.last_login = datetime.utcnow()

            db.session.commit()
            login_user(user)

            return redirect(url_for("dashboard"))

        except Exception as e:
            logger.exception("OAuth failed")
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route("/logout")
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # ---------------- API ----------------

    @app.route("/api/user")
    def get_user():
        if current_user.is_authenticated:
            return jsonify({"success": True, "user": current_user.to_dict()})
        return jsonify({"success": False}), 401

    @app.route("/api/test")
    def test():
        return jsonify({
            "success": True,
            "oauth_enabled": oauth_enabled,
            "timestamp": datetime.utcnow().isoformat()
        })


# ------------------- RUN -------------------

app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_ENV") == "development"
    )