from flask import Flask, render_template, request, redirect, session
from flask_socketio import SocketIO, send
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import os
import json

load_dotenv()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
print("ADMIN =", ADMIN_PASSWORD)

app = Flask(__name__)
app.secret_key = "secret123"
socketio = SocketIO(app)

RECIPES_FILE = "recettes.json"
AUTORISES_FILE = "autorises.json"
NON_AUTORISES_FILE = "non_autorises.json"
FAVORIS_FILE = "favoris.json"

if not os.path.exists(FAVORIS_FILE):
    with open(FAVORIS_FILE, "w") as f:
        json.dump([], f)

# 🔧 Création fichiers si inexistants
for file in [RECIPES_FILE, AUTORISES_FILE, NON_AUTORISES_FILE]:
    if not os.path.exists(file):
        with open(file, "w", encoding="utf-8") as f:
            json.dump([], f)

# Charger données
with open(RECIPES_FILE, "r", encoding="utf-8") as f:
    recipes = json.load(f)

# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    with open(AUTORISES_FILE, "r", encoding="utf-8") as f:
        autorises = json.load(f)

    with open(NON_AUTORISES_FILE, "r", encoding="utf-8") as f:
        non_autorises = json.load(f)

    if request.method == 'POST':
        username = request.form['username']

        # 🔐 ADMIN AVEC MOT DE PASSE
        if username == "admin":
            password = request.form.get('password')

            if password == ADMIN_PASSWORD:
                session['username'] = username
                session['role'] = "admin"
                return redirect('/')
            else:
                error = "Mot de passe admin incorrect"

        # 👤 USER autorisé
        elif username in autorises:
            session['username'] = username
            session['role'] = "user"
            return redirect('/')

        # ❌ USER refusé
        elif username in non_autorises:
            error = "Accès refusé"

        # 🆕 NOUVEL UTILISATEUR
        else:
            if username not in non_autorises:
                non_autorises.append(username)

                with open(NON_AUTORISES_FILE, "w", encoding="utf-8") as f:
                    json.dump(non_autorises, f, indent=4)

                socketio.emit('new_user', username)

            error = "⏳ En attente de validation par admin"

    return render_template("login.html", error=error)# ---------------- ACCEPTER / REFUSER ----------------
@app.route('/validate_user', methods=['POST'])
def validate_user():
    username = request.form['username']
    action = request.form['action']

    with open(AUTORISES_FILE, "r", encoding="utf-8") as f:
        autorises = json.load(f)

    with open(NON_AUTORISES_FILE, "r", encoding="utf-8") as f:
        non_autorises = json.load(f)

    if action == "autoriser":
        autorises.append(username)
        with open(AUTORISES_FILE, "w", encoding="utf-8") as f:
            json.dump(autorises, f, indent=4)

        session['username'] = username
        session['role'] = "user"

    else:
        non_autorises.append(username)
        with open(NON_AUTORISES_FILE, "w", encoding="utf-8") as f:
            json.dump(non_autorises, f, indent=4)

    return redirect('/')

# ---------------- ACCUEIL ----------------
@app.route('/')
def index():
    cat = request.args.get('cat')
    sub = request.args.get('sub')
    search = request.args.get('search')

    filtered = recipes

    if cat:
        filtered = [r for r in filtered if r.get("categorie") == cat]

    if sub:
        filtered = [r for r in filtered if r.get("sous_categorie") == sub]

    if search:
        filtered = [
            r for r in filtered
            if search.lower() in r.get("title", "").lower()
        ]

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

        recipe = {
    "title": request.form['title'],
    "ingredients": request.form['ingredients'],
    "preparation": request.form['preparation'],
    "cuisson": request.form['cuisson'],
    "astuce": request.form['astuce'],
    "image": filename,
    "categorie": request.form['categorie'],
    "sous_categorie": request.form['sous_categorie']
}

        recipes.append(recipe)

        with open(RECIPES_FILE, "w", encoding="utf-8") as f:
            json.dump(recipes, f, indent=4)

        return redirect('/')

    return render_template("add.html")

# ---------------- DELETE ----------------
@app.route('/delete/<int:id>')
def delete(id):
    if 'username' not in session:
        return redirect('/login')

    if session.get("role") != "admin":
        return "Accès refusé"

    if id < len(recipes):
        recipes.pop(id)

        with open(RECIPES_FILE, "w", encoding="utf-8") as f:
            json.dump(recipes, f, indent=4)

    return redirect('/')

# ---------------- EDIT ----------------
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    if 'username' not in session:
        return redirect('/login')

    if id >= len(recipes):
        return redirect('/')

    recipe = recipes[id]

    if request.method == 'POST':
        recipe['title'] = request.form['title']
        recipe['ingredients'] = request.form['ingredients']
        recipe['preparation'] = request.form['preparation']
        recipe['cuisson'] = request.form['cuisson']
        recipe['astuce'] = request.form['astuce']

        with open(RECIPES_FILE, "w", encoding="utf-8") as f:
            json.dump(recipes, f, indent=4)

        return redirect('/')

    return render_template("edit.html", recipe=recipe, id=id)

# ---------------- CHAT ----------------
@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect('/login')
    return render_template("chat.html", username=session['username'])

@socketio.on('message')
def handle_message(msg):
    send(msg, broadcast=True)

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
        return "Accès refusé"

    with open(AUTORISES_FILE, "r", encoding="utf-8") as f:
        autorises = json.load(f)

    with open(NON_AUTORISES_FILE, "r", encoding="utf-8") as f:
        non_autorises = json.load(f)

    return render_template("admin.html", autorises=autorises, non_autorises=non_autorises)
# ---------------- ADMIN ACTIONS ----------------
@app.route('/admin/autoriser/<username>')
def admin_autoriser(username):
    if session.get("role") != "admin":
        return "Accès refusé"

    with open(AUTORISES_FILE, "r", encoding="utf-8") as f:
        autorises = json.load(f)

    if username not in autorises:
        autorises.append(username)

    with open(AUTORISES_FILE, "w", encoding="utf-8") as f:
        json.dump(autorises, f, indent=4)

    return redirect('/admin')


@app.route('/admin/refuser/<username>')
def admin_refuser(username):
    if session.get("role") != "admin":
        return "Accès refusé"

    with open(NON_AUTORISES_FILE, "r", encoding="utf-8") as f:
        non_autorises = json.load(f)

    if username not in non_autorises:
        non_autorises.append(username)

    with open(NON_AUTORISES_FILE, "w", encoding="utf-8") as f:
        json.dump(non_autorises, f, indent=4)

    return redirect('/admin')

@app.route('/admin/delete_user/<username>')
def delete_user(username):
    if session.get("role") != "admin":
        return "Accès refusé"

    with open(AUTORISES_FILE, "r", encoding="utf-8") as f:
        autorises = json.load(f)

    with open(NON_AUTORISES_FILE, "r", encoding="utf-8") as f:
        non_autorises = json.load(f)

    if username in autorises:
        autorises.remove(username)

    if username in non_autorises:
        non_autorises.remove(username)

    with open(AUTORISES_FILE, "w", encoding="utf-8") as f:
        json.dump(autorises, f, indent=4)

    with open(NON_AUTORISES_FILE, "w", encoding="utf-8") as f:
        json.dump(non_autorises, f, indent=4)

    return redirect('/admin')

#--------------------FAVORIS------------------------------
@app.route('/favori/<int:id>')
def toggle_favori(id):
    if 'username' not in session:
        return redirect('/login')

    # charger favoris
    with open(FAVORIS_FILE, "r", encoding="utf-8") as f:
        favoris = json.load(f)

    user = session['username']
    entry = {"user": user, "id": id}

    # toggle
    if entry in favoris:
        favoris.remove(entry)
    else:
        favoris.append(entry)

    # sauvegarde
    with open(FAVORIS_FILE, "w", encoding="utf-8") as f:
        json.dump(favoris, f, indent=4)

    return redirect('/')

#--------------------RUN------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)