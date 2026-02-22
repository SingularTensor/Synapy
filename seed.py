from app import app
from database import db, GameType, User

INITIAL_GAMES = [
    # General (Free)
    {
        'slug': 'sequence-memory', 'name': 'Sequence Memory', 'description': 'Remember sequence', 'cognitive_domain': 'working_memory', 'icon': 'grid', 'color': '#8B5CF6', 'access_level': 'free', 'industry': 'General Puzzles'
    },
    {
        'slug': 'speed-dart', 'name': 'Speed Dart', 'description': 'Find and hit the target', 'cognitive_domain': 'processing_speed', 'icon': 'zap', 'color': '#F59E0B', 'access_level': 'free', 'industry': 'General Puzzles'
    },
    {
        'slug': 'mental-math', 'name': 'Mental Math', 'description': 'Arithmetic under pressure', 'cognitive_domain': 'mental_math', 'icon': 'calculator', 'color': '#EF4444', 'access_level': 'free', 'industry': 'General Puzzles'
    },
    {
        'slug': 'box-adding', 'name': 'Box Adding', 'description': 'Add flashed values from highlighted boxes', 'cognitive_domain': 'mental_math', 'icon': 'plus-square', 'color': '#22C55E', 'access_level': 'free', 'industry': 'General Puzzles'
    },
    {
        'slug': 'color-word', 'name': 'Color Word', 'description': 'Tap the ink color, not the word', 'cognitive_domain': 'attention', 'icon': 'palette', 'color': '#F97316', 'access_level': 'free', 'industry': 'General Puzzles'
    },
    # Retail / Foodservice (Premium)
    {
        'slug': 'drive-thru-multitasking', 'name': 'Drive-Thru Multi-Tasking', 'description': 'Handle audio orders while packing bags visual', 'cognitive_domain': 'attention', 'icon': 'headphones', 'color': '#EC4899', 'access_level': 'premium', 'industry': 'Foodservice'
    },
    {
        'slug': 'inventory-spatial-pack', 'name': 'Inventory Spatial Pack', 'description': 'Optimize box packing based on dimensions', 'cognitive_domain': 'pattern_recognition', 'icon': 'box', 'color': '#3B82F6', 'access_level': 'premium', 'industry': 'Logistics'
    },
    {
        'slug': 'customer-escalation-nlp', 'name': 'Customer Escalation NLP', 'description': 'Identify emotional cues in support tickets', 'cognitive_domain': 'verbal_fluency', 'icon': 'message-square', 'color': '#10B981', 'access_level': 'premium', 'industry': 'Retail'
    },
    {
        'slug': 'pos-register-speed', 'name': 'POS Register Speed', 'description': 'Rapidly calculate change and hit correct buttons', 'cognitive_domain': 'mental_math', 'icon': 'dollar-sign', 'color': '#F59E0B', 'access_level': 'premium', 'industry': 'Retail'
    }
]


def seed():
    with app.app_context():
        db.drop_all()
        db.create_all()

        for game_data in INITIAL_GAMES:
            game = GameType(**game_data)
            db.session.add(game)

        admin = User(username='admin', email='admin@synapy.com', is_admin=True)
        admin.set_password('admin123')
        db.session.add(admin)

        db.session.commit()
        print(f'Seeded {len(INITIAL_GAMES)} game types and admin user')


if __name__ == '__main__':
    seed()
