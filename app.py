import google.generativeai as genai
from sqlalchemy.exc import IntegrityError
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint


from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import (
    LoginManager, UserMixin,
    login_user, logout_user,
    login_required, current_user
)

app = Flask(__name__)


app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///habits.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "dev-secret"

genai.configure(api_key="PASTE_YOUR_API_KEY_HERE")
model = genai.GenerativeModel("gemini-pro")

db = SQLAlchemy(app)


login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


class Habit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, unique=True)
    color = db.Column(db.String(7), default="#3e7ce0", nullable=False)
    goal_type = db.Column(db.String(20), default="daily")
    target_per_day = db.Column(db.Integer, default=1)
    created_at = db.Column(db.Date, default=date.today)

class Checkin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey('habit.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    __table_args__ = (
        UniqueConstraint('habit_id', 'date', name='uix_habit_date'),
    )

Habit.checkins = db.relationship(
    'Checkin',
    backref='habit',
    cascade='all, delete-orphan'
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


with app.app_context():
    db.create_all()


def get_streak(habit, today):
    has = {c.date for c in habit.checkins}
    s, d = 0, today

    
    while d >= habit.created_at and d in has:
        s += 1
        d -= timedelta(days=1)

    return s



@app.route("/")
@login_required  
def index():
    today = date.today()
    habits = Habit.query.order_by(Habit.created_at.desc()).all()
    days = [today - timedelta(days=i) for i in reversed(range(7))]
    check_map = {
        (c.habit_id, c.date)
        for c in Checkin.query.filter(Checkin.date >= days[0]).all()
    }
    streaks = {h.id: get_streak(h, today) for h in habits}
    print(check_map)

    return render_template(
        'index.html',
        habits=habits,
        days=days,
        check_map=check_map,
        today=today,
        streaks=streaks
    )

@app.route("/habits")
@login_required
def habits():
    habits = Habit.query.order_by(Habit.created_at.desc()).all()
    return render_template("habits.html", habits=habits)

@app.route("/habits/create", methods=["POST"])
@login_required
def create_habit():
    name = request.form.get('name', '').strip()
    color = request.form.get('color', "#3b82f6").strip()

    if not name:
        flash("Name is required", "error")
        return redirect(url_for("habits"))

    try:
        habit = Habit(name=name, color=color)
        db.session.add(habit)
        db.session.commit()
        flash("Habit created successfully", "success")

    except IntegrityError:
        db.session.rollback()
        flash("Habit name must be unique", "error")

    return redirect(url_for("habits"))

@app.route("/analytics.json")
@login_required
def analytics_json():
    today = date.today()
    days = [today - timedelta(days=i) for i in reversed(range(7))]
    labels = [d.strftime('%a') for d in days]
    counts = [Checkin.query.filter_by(date=d).count() for d in days]
    return jsonify({"labels": labels, "data": counts})

@app.route('/analytics')
@login_required
def analytics_page():
    habits = Habit.query.order_by(Habit.created_at.desc()).all()
    return render_template("analytics.html", habits=habits)

@app.route('/habits/<int:habit_id>/delete', methods=["POST"])
@login_required
def delete_habit(habit_id):
    habit = Habit.query.get_or_404(habit_id)
    db.session.delete(habit)
    db.session.commit()
    flash("Habit deleted", "success")
    return redirect(url_for('habits'))

@app.route('/toggle', methods=["POST"])
@login_required
def toggle():
    hid = int(request.form['habit_id'])
    d = date.fromisoformat(request.form['date'])

    existing = Checkin.query.filter_by(
        habit_id=hid,
        date=d
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        status = False
    else:
        checkin = Checkin(habit_id=hid, date=d)
        db.session.add(checkin)
        db.session.commit()
        status = True

    print(f"Got toggle request: habit_id={hid}, date={d}")
    return jsonify({"ok": True, "checked": status})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("index"))

        flash("Invalid username or password", "error")

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("All fields required", "error")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Username already exists", "error")
            return redirect(url_for("register"))

        user = User(username=username)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# ---------- GOOGLE GEMINI CONFIG ----------


@app.route("/ai-advice", methods=["POST"])
@login_required
def ai_advice():
    habit_name = request.form.get("habit", "your habit")
    streak = request.form.get("streak", "0")

    prompt = (
        f"I am tracking a habit called '{habit_name}'. "
        f"My current streak is {streak} days. "
        "Give me short, practical motivation or advice to stay consistent."
    )

    try:
        response = model.generate_content(prompt)
        return jsonify({"advice": response.text})
    except Exception:
        return jsonify({
            "advice": "Stay consistent. Small daily actions lead to big results."
        })



if __name__ == "__main__":
    app.run(debug=True, port=3535)
