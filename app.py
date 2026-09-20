import time
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'fireboy_watergirl_secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory storage for active game rooms
# Structure: { room_id: { players, current_level, level_start_time, total_paused_ms, pause_start_time, is_paused, scores } }
rooms = {}

TOTAL_LEVELS = 3  # Total levels in the game

@socketio.on('join_game')
def handle_join_game(data):
    room_id = data.get('roomId')
    role = data.get('role')  # 'fireboy' or 'watergirl'
    
    join_room(room_id)
    
    if room_id not in rooms:
        rooms[room_id] = {
            'players': {},
            'current_level': 1,
            'level_start_time': None,
            'total_paused_ms': 0,
            'pause_start_time': None,
            'is_paused': False,
            'scores': []
        }
        
    room = rooms[room_id]
    room['players'][role] = request.sid
    
    emit('player_joined', {'role': role, 'players': list(room['players'].keys())}, to=room_id)
    
    # Start level timer when both players connect
    if 'fireboy' in room['players'] and 'watergirl' in room['players'] and room['level_start_time'] is None:
        start_new_level(room)
        emit('game_start', {'level': room['current_level']}, to=room_id)

@socketio.on('player_visibility_change')
def handle_visibility_change(data):
    """
    Handles tab-switching / window minimizing.
    Pauses active timer and sends resume panel triggers.
    """
    room_id = data.get('roomId')
    is_visible = data.get('isVisible')
    role = data.get('role')
    
    if room_id not in rooms:
        return
        
    room = rooms[room_id]
    current_time_ms = int(time.time() * 1000)
    
    if not is_visible and not room['is_paused']:
        # Player switched tabs -> Pause game & timer
        room['is_paused'] = True
        room['pause_start_time'] = current_time_ms
        emit('game_paused', {
            'pausedBy': role,
            'message': f'{role.capitalize()} switched tabs. Click Resume when ready!'
        }, to=room_id)
        
    elif is_visible and room['is_paused']:
        # Request to resume
        emit('resume_request', {'requestedBy': role}, to=room_id)

@socketio.on('confirm_resume')
def handle_confirm_resume(data):
    """Resumes timer and syncs state when players click the Resume panel."""
    room_id = data.get('roomId')
    if room_id not in rooms:
        return
        
    room = rooms[room_id]
    if room['is_paused'] and room['pause_start_time']:
        current_time_ms = int(time.time() * 1000)
        # Add inactive tab duration to paused time accumulator
        room['total_paused_ms'] += (current_time_ms - room['pause_start_time'])
        room['pause_start_time'] = None
        room['is_paused'] = False
        
        emit('game_resumed', {'level': room['current_level']}, to=room_id)

@socketio.on('complete_level')
def handle_complete_level(data):
    room_id = data.get('roomId')
    if room_id not in rooms or rooms[room_id]['is_paused']:
        return
        
    room = rooms[room_id]
    current_time_ms = int(time.time() * 1000)
    
    # Compute net active time (excluding tab pause duration)
    total_elapsed_ms = current_time_ms - room['level_start_time']
    active_time_sec = max(0, int((total_elapsed_ms - room['total_paused_ms']) / 1000))
    
    # Score formula: 1000 base points minus 5 points per active second (min score: 100)
    level_score = max(100, 1000 - (active_time_sec * 5))
    room['scores'].append({
        'level': room['current_level'],
        'time_seconds': active_time_sec,
        'score': level_score
    })
    
    total_game_score = sum(item['score'] for item in room['scores'])
    
    if room['current_level'] < TOTAL_LEVELS:
        room['current_level'] += 1
        start_new_level(room)
        emit('level_cleared', {
            'levelCleared': room['current_level'] - 1,
            'timeTaken': active_time_sec,
            'levelScore': level_score,
            'nextLevel': room['current_level']
        }, to=room_id)
    else:
        # All levels completed -> Unlock surprise gift
        emit('game_completed', {
            'totalScore': total_game_score,
            'levelBreakdown': room['scores'],
            'rewardCode': f"GIFT-FIRE-WATER-{total_game_score}"
        }, to=room_id)

def start_new_level(room):
    room['level_start_time'] = int(time.time() * 1000)
    room['total_paused_ms'] = 0
    room['pause_start_time'] = None
    room['is_paused'] = False

@socketio.on('disconnect')
def handle_disconnect():
    for room_id, room in list(rooms.items()):
        for role, sid in list(room['players'].items()):
            if sid == request.sid:
                emit('player_left', {'role': role}, to=room_id)
                del room['players'][role]
                if not room['players']:
                    del rooms[room_id]
                break

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)