from flask import Flask
from flask_login import LoginManager
from database import db, User
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///synapy.db'
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))

db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

from routes import *

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
