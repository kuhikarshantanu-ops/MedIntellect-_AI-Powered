from flask import Flask, render_template, request, redirect, url_for, flash, session
from config import Config
from utils.db import get_db_connection
from services.auth_service import AuthService
from services.doctor_verification_service import DoctorVerificationService
from routes.patient_routes import patient_bp
from routes.doctor_routes import doctor_bp
from routes.admin_routes import admin_bp

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY or "medintellect_secret_key"

# Register Blueprints
app.register_blueprint(patient_bp)
app.register_blueprint(doctor_bp)
app.register_blueprint(admin_bp)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    specializations = DoctorVerificationService.get_all_specializations()

    if request.method == "POST":
        try:
            role_id = int(request.form["role"])
            form_data = {
                "role_id":   role_id,
                "full_name": request.form["full_name"],
                "email":     request.form["email"],
                "phone":     request.form["phone"],
                "gender":    request.form["gender"],
                "dob":       request.form["dob"],
                "password":  request.form["password"],
            }

            # ── PATIENT registration (unchanged) ─────────────────────────
            if role_id == 3:
                AuthService.register_user(form_data)
                flash("Registration Successful! Please sign in to access your portal.", "success")
                return redirect(url_for("login"))

            # ── DOCTOR registration — secure multi-layer verification ──────
            elif role_id == 2:
                doctor_form = {
                    "license_number":   request.form.get("license_number", ""),
                    "qualification":    request.form.get("qualification", ""),
                    "specialization_id":request.form.get("specialization_id", ""),
                    "hospital_name":    request.form.get("hospital_name", ""),
                    "experience_years": request.form.get("experience_years", ""),
                }

                # 1. Pre-validate doctor credentials & files BEFORE user creation
                DoctorVerificationService.pre_validate(doctor_form, request.files)

                # 2. Create user account with status=Pending
                user_id = AuthService.register_user(form_data)

                # 3. Process verification documents and save record
                try:
                    DoctorVerificationService.register_doctor(
                        user_id=user_id,
                        form_data=doctor_form,
                        files=request.files,
                        base_path=app.root_path
                    )
                except Exception as doc_err:
                    from models.user_model import UserModel
                    # Rollback / cleanup user account if document processing failed
                    conn = get_db_connection()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
                    conn.commit()
                    cur.close()
                    conn.close()
                    raise doc_err

                flash(
                    "✅ Doctor registration submitted successfully! "
                    "Your professional documents are under verification. "
                    "You will receive access after admin approval.",
                    "success"
                )
                return redirect(url_for("doctor_pending"))

            else:
                flash("Invalid account type selected.", "danger")

        except Exception as e:
            flash(str(e), "danger")

    return render_template("auth/register.html", specializations=specializations)


@app.route("/doctor/pending")
def doctor_pending():
    """Status page shown to doctors awaiting verification."""
    user_id = session.get("user_id")
    verification = None
    if user_id:
        verification = DoctorVerificationService.get_doctor_status(user_id)
    return render_template("auth/doctor_pending.html", verification=verification)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please fill in both email and password.", "danger")
            return render_template("auth/login.html")

        try:
            user = AuthService.authenticate_user(email, password)
        except Exception as e:
            msg = str(e)
            if msg.startswith("DOCTOR_PENDING:"):
                flash(msg.split(":", 1)[1], "warning")
                return render_template("auth/login.html", show_pending_link=True)
            elif msg.startswith("DOCTOR_REJECTED:"):
                flash(msg.split(":", 1)[1], "danger")
                return render_template("auth/login.html")
            elif msg.startswith("ACCOUNT_BLOCKED:"):
                flash(msg.split(":", 1)[1], "danger")
                return render_template("auth/login.html")
            else:
                flash(msg, "danger")
                return render_template("auth/login.html")

        if user:
            session["user_id"]   = user["user_id"]
            session["full_name"] = user["full_name"]
            session["role_id"]   = user["role_id"]
            session["email"]     = user["email"]

            flash(f"Welcome back, {user['full_name']}!", "success")

            if user["role_id"] == 3:
                return redirect(url_for("patient.dashboard"))
            elif user["role_id"] == 2:
                return redirect(url_for("doctor.dashboard"))
            elif user["role_id"] == 1:
                return redirect(url_for("admin.dashboard"))

            return redirect(url_for("home"))
        else:
            flash("Invalid email or password. Please try again.", "danger")

    return render_template("auth/login.html")




@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("home"))


@app.route("/test-db")
def test_db():
    if session.get("role_id") != 1:
        return redirect(url_for("home"))
    try:
        connection = get_db_connection()
        if connection.is_connected():
            connection.close()
            return "<h2>✅ Database Connected Successfully!</h2>"
    except Exception as e:
        return f"<h2>❌ Error: {e}</h2>"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)