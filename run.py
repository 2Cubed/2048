from flask import Flask, render_template
from flask_socketio import SocketIO

import asyncio
from requests import Session
from beam_interactive import start
from beam_interactive import proto
from math import copysign

from threading import Thread
from sys import exit


path = "https://beam.pro/api/v1"
auth = {
    "username": "USERNAME",
    "password": "PASSWORD"
}

threshold = 0.8  # the percent of viewers required to take an action

joy_to_dir = [
    {
        1:  1,  # joystick right = move right
        -1: 3   # joystick left  = move left
    },
    {
        1:  2,  # joystick down  = move down
        -1: 0   # joystick up    = move up
    }
]

app = Flask(__name__)
app.config["SECRET_KEY"] = "mappa"

socketio = SocketIO(app, async_mode='threading')


@app.route("/")
def load_game():
    return render_template("index.html")


def login(session, username, password):
    """Log into the Beam servers via the API."""
    auth = dict(username=username, password=password)
    return session.post(path + "/users/login", auth).json()


def get_tetris(session, channel):
    """Retrieve interactive connection information."""
    return session.get(path + "/tetris/{id}/robot".format(id=channel)).json()


def on_error(error, conn):
    print('Oh no, there was an error!')
    print(error.message)


def progress(target, code, progress):
    update = proto.ProgressUpdate()
    prog = update.progress.add()
    prog.target = prog.__getattribute__(target)
    prog.code = code
    prog.progress = progress
    return update


def on_report(report, conn):
    keys = list()
    updates = list()

    for joystick in report.joystick:
        if abs(joystick.info.mean) > threshold:
            key = joy_to_dir[joystick.axis][copysign(1, joystick.info.mean)]
            keys.append(key)
            update = progress(
                "JOYSTICK",
                joystick.axis,
                min(0.999, abs(joystick.info.mean / threshold))
            )
        else:
            update = progress("JOYSTICK", joystick.axis, 0)
            updates.append(update)

    for update in updates:
        conn.send(update)

    for key in keys:
        print("PRESSING:", key)
        with app.test_request_context('/'):
            socketio.emit("move", key, namespace="/2048")


loop = asyncio.get_event_loop()


@asyncio.coroutine
def connect():
    session = Session()
    channel_id = login(session, **auth)['channel']['id']

    data = get_tetris(session, channel_id)

    conn = yield from start(data['address'], channel_id, data['key'], loop)

    handlers = {
        proto.id.error: on_error,
        proto.id.report: on_report
    }

    while (yield from conn.wait_message()):
        decoded, packet_bytes = conn.get_packet()
        packet_id = proto.id.get_packet_id(decoded)

        if decoded is None:
            print('We got a bunch of unknown bytes.')
            print(packet_id)
        elif packet_id in handlers:
            handlers[packet_id](decoded, conn)
        else:
            print("We got packet {} but didn't handle it!".format(packet_id))

    conn.close()


thread = Thread(target=loop.run_until_complete, args=(connect(),))
thread.setDaemon(True)
thread.start()

if __name__ == "__main__":
    try:
        socketio.run(app, port=8023)
    except KeyboardInterrupt:
        exit()
