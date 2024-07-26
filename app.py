from app import create_app
from scheduler import start

app = create_app()

if __name__ == '__main__':
    start()
    app.run(debug=True)