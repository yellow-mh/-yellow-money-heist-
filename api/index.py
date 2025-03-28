from flask import Flask
app = Flask(__name__)

@app.route('/')
def hello():
    return "Yellow Money Heist - Coming Soon"

if __name__ == '__main__':
    app.run()
