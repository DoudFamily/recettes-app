from flask import Flask, render_template, request, redirect, session
from flask_socketio import SocketIO, send
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import sqlite3

load_dotenv()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

app = Flask(__name__)
app.secret_key = "secret123"
socketio = SocketIO(app)

DB_FILE = "database.db"
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

# ---------------- TABLES ----------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS autorises (
    username TEXT UNIQUE
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS non_autorises (
    username TEXT UNIQUE
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS recettes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    ingredients TEXT,
    preparation TEXT,
    cuisson TEXT,
    astuce TEXT,
    image TEXT,
    categorie TEXT,
    sous_categorie TEXT
)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS favoris (
    user TEXT,
    recipe_id INTEGER
)
""")
conn.commit()


# ---------------- HELPERS ----------------
def get_autorises():
    cursor.execute("SELECT username FROM autorises")
    return [row[0] for row in cursor.fetchall()]

def get_non_autorises():
    cursor.execute("SELECT username FROM non_autorises")
    return [row[0] for row in cursor.fetchall()]

def get_recipes():
    cursor.execute("SELECT id, title, ingredients, preparation, cuisson, astuce, image, categorie, sous_categorie FROM recettes")
    rows = cursor.fetchall()
    return [
        {
            "id": r[0], "title": r[1], "ingredients": r[2],
            "preparation": r[3], "cuisson": r[4], "astuce": r[5],
            "image": r[6], "categorie": r[7], "sous_categorie": r[8]
        }
        for r in rows
    ]


# ---------------- AUTH GUARD ----------------
@app.before_request
def verifier_acces():
    if 'username' in session and session.get('role') != 'admin':
        cursor.execute(
            "SELECT username FROM autorises WHERE username=?",
            (session['username'],)
        )
        user = cursor.fetchone()
        if not user:
            session.clear()
            return redirect('/login')


# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    autorises = get_autorises()
    non_autorises = get_non_autorises()

    if request.method == 'POST':
        username = request.form['username']

        if username == "admin":
            password = request.form.get('password')
            if password == ADMIN_PASSWORD:
                session['username'] = username
                session['role'] = "admin"
                return redirect('/')
            else:
                error = "Mot de passe admin incorrect"

        elif username in autorises:
            session['username'] = username
            session['role'] = "user"
            return redirect('/')

        elif username in non_autorises:
            error = "Acces refuse"

        else:
            cursor.execute(
                "INSERT OR IGNORE INTO non_autorises (username) VALUES (?)",
                (username,)
            )
            conn.commit()
            socketio.emit('new_user', username)
            error = "En attente de validation par admin"

    return render_template("login.html", error=error)


# ---------------- ACCEPTER / REFUSER ----------------
@app.route('/validate_user', methods=['POST'])
def validate_user():
    username = request.form['username']
    action = request.form['action']

    if action == "autoriser":
        cursor.execute("INSERT OR IGNORE INTO autorises (username) VALUES (?)", (username,))
        cursor.execute("DELETE FROM non_autorises WHERE username=?", (username,))
    else:
        cursor.execute("INSERT OR IGNORE INTO non_autorises (username) VALUES (?)", (username,))

    conn.commit()
    return redirect('/admin')


# ---------------- ACCUEIL ----------------
@app.route('/')
def index():
    cat = request.args.get('cat')
    sub = request.args.get('sub')
    search = request.args.get('search')

    filtered = get_recipes()

    if cat:
        filtered = [r for r in filtered if r.get("categorie") == cat]
    if sub:
        filtered = [r for r in filtered if r.get("sous_categorie") == sub]
    if search:
        filtered = [r for r in filtered if search.lower() in r.get("title", "").lower()]

    return render_template(
        "index.html",
        recipes=filtered,
        username=session.get("username"),
        role=session.get("role"),
        cat=cat,
        sub=sub,
        search=search
    )


# ---------------- AJOUT ----------------
@app.route('/add', methods=['GET', 'POST'])
def add():
    if 'username' not in session:
        return redirect('/login')

    if request.method == 'POST':
        image_file = request.files['image']
        filename = ""
        if image_file and image_file.filename != "":
            filename = secure_filename(image_file.filename)
            image_path = os.path.join("static/images", filename)
            image_file.save(image_path)

        cursor.execute(
            "INSERT INTO recettes (title, ingredients, preparation, cuisson, astuce, image, categorie, sous_categorie) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                request.form['title'],
                request.form['ingredients'],
                request.form['preparation'],
                request.form['cuisson'],
                request.form['astuce'],
                filename,
                request.form['categorie'],
                request.form['sous_categorie']
            )
        )
        conn.commit()
        return redirect('/')

    return render_template("add.html")


# ---------------- DELETE ----------------
@app.route('/delete/<int:id>')
def delete(id):
    if 'username' not in session:
        return redirect('/login')
    if session.get("role") != "admin":
        return "Acces refuse"

    cursor.execute("DELETE FROM recettes WHERE id=?", (id,))
    conn.commit()
    return redirect('/')


# ---------------- EDIT ----------------
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if 'username' not in session:
        return redirect('/login')

    cursor.execute("SELECT * FROM recettes WHERE id=?", (id,))
    row = cursor.fetchone()
    if not row:
        return redirect('/')

    recipe = {
        "id": row[0], "title": row[1], "ingredients": row[2],
        "preparation": row[3], "cuisson": row[4], "astuce": row[5],
        "image": row[6], "categorie": row[7], "sous_categorie": row[8]
    }

    if request.method == 'POST':
        cursor.execute(
            "UPDATE recettes SET title=?, ingredients=?, preparation=?, cuisson=?, astuce=? WHERE id=?",
            (
                request.form['title'],
                request.form['ingredients'],
                request.form['preparation'],
                request.form['cuisson'],
                request.form['astuce'],
                id
            )
        )
        conn.commit()
        return redirect('/')

    return render_template("edit.html", recipe=recipe, id=id)


# ---------------- CHAT ----------------
messages_store = {}

def get_room(user1, user2):
    return "_".join(sorted([user1, user2]))

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect('/login')

    autorises = get_autorises()
    users = [u for u in autorises if u != session['username']]
    if session['username'] != 'admin':
        users.append('admin')

    return render_template("chat.html", username=session['username'], users=users)

@app.route('/chat/<destinataire>')
def chat_prive(destinataire):
    if 'username' not in session:
        return redirect('/login')

    room = get_room(session['username'], destinataire)
    historique = messages_store.get(room, [])

    return render_template(
        "chat_prive.html",
        username=session['username'],
        destinataire=destinataire,
        room=room,
        historique=historique
    )

@socketio.on('message_prive')
def handle_prive(data):
    room = data['room']
    msg = {"from": data['from'], "text": data['text']}
    if room not in messages_store:
        messages_store[room] = []
    messages_store[room].append(msg)
    socketio.emit('message_prive', msg, room=room)

@socketio.on('join')
def on_join(data):
    from flask_socketio import join_room
    join_room(data['room'])


# ---------------- LOGOUT ----------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')


# ---------------- ADMIN PANEL ----------------
@app.route('/admin')
def admin():
    if 'username' not in session:
        return redirect('/login')
    if session.get("role") != "admin":
        return "Acces refuse"

    autorises = get_autorises()
    non_autorises = get_non_autorises()

    return render_template("admin.html", autorises=autorises, non_autorises=non_autorises)


# ---------------- ADMIN ACTIONS ----------------
@app.route('/admin/autoriser/<username>')
def admin_autoriser(username):
    if session.get("role") != "admin":
        return "Acces refuse"

    cursor.execute("INSERT OR IGNORE INTO autorises (username) VALUES (?)", (username,))
    cursor.execute("DELETE FROM non_autorises WHERE username=?", (username,))
    conn.commit()
    return redirect('/admin')


@app.route('/admin/refuser/<username>')
def admin_refuser(username):
    if session.get("role") != "admin":
        return "Acces refuse"

    cursor.execute("INSERT OR IGNORE INTO non_autorises (username) VALUES (?)", (username,))
    cursor.execute("DELETE FROM autorises WHERE username=?", (username,))
    conn.commit()
    return redirect('/admin')


@app.route('/admin/delete_user/<username>')
def delete_user(username):
    if session.get("role") != "admin":
        return "Acces refuse"

    cursor.execute("DELETE FROM autorises WHERE username=?", (username,))
    cursor.execute("DELETE FROM non_autorises WHERE username=?", (username,))
    conn.commit()
    return redirect('/admin')


# ---------------- FAVORIS ----------------
@app.route('/favori/<int:id>')
def toggle_favori(id):
    if 'username' not in session:
        return redirect('/login')

    user = session['username']
    cursor.execute("SELECT * FROM favoris WHERE user=? AND recipe_id=?", (user, id))
    existing = cursor.fetchone()

    if existing:
        cursor.execute("DELETE FROM favoris WHERE user=? AND recipe_id=?", (user, id))
    else:
        cursor.execute("INSERT INTO favoris (user, recipe_id) VALUES (?, ?)", (user, id))

    conn.commit()
    return redirect('/')


# ---------------- RUN ----------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)