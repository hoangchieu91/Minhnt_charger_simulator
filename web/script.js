const socket = io();
const grid = document.getElementById('slaves-grid');
const template = document.getElementById('slave-template');
const socketStatus = document.getElementById('socket-status');
const socketDot = document.getElementById('socket-dot');

const STATE_NAMES = ["INIT", "IDLE", "STANDBY", "CHARGING", "FINISH", "ERROR"];

function updateClock() {
    document.getElementById('clock').textContent = new Date().toLocaleTimeString();
}
setInterval(updateClock, 1000);

function initUI() {
    grid.innerHTML = '';
    // Show 5 slaves: IDs 2, 3, 4, 5, 6
    for (let i = 2; i <= 6; i++) {
        const html = template.innerHTML.replace(/{{id}}/g, i);
        const div = document.createElement('div');
        div.innerHTML = html;
        grid.appendChild(div.firstElementChild);
    }
}

initUI();

socket.on('connect', () => {
    socketStatus.textContent = 'Online';
    socketDot.classList.add('online');
});

socket.on('disconnect', () => {
    socketStatus.textContent = 'Offline';
    socketDot.classList.remove('online');
});

socket.on('update', (data) => {
    // Update Meter
    if (data.meter) {
        document.getElementById('meter-e').textContent = data.meter.e.toFixed(2);
        document.getElementById('meter-p').textContent = data.meter.p.toFixed(3);
        document.getElementById('meter-v').textContent = data.meter.v.toFixed(1);
        document.getElementById('meter-a').textContent = data.meter.a.toFixed(3);
    }

    // Update Slaves
    if (data.slaves) {
        for (const [id, s] of Object.entries(data.slaves)) {
            const card = document.getElementById(`slave-${id}`);
            if (!card) continue;

            card.querySelector('.val-v').textContent = s.v;
            card.querySelector('.val-a').textContent = s.a.toFixed(2);
            card.querySelector('.val-p').textContent = s.p;
            card.querySelector('.val-e').textContent = s.e.toFixed(3);
            card.querySelector('.val-t').textContent = s.t;
            card.querySelector('.val-sn').textContent = s.sn;
            
            const stateText = card.querySelector('.status-text');
            stateText.textContent = STATE_NAMES[s.state] || 'UNKNOWN';
            
            if (s.state === 3) { // CHARGING
                card.classList.add('charging');
                stateText.style.background = 'rgba(16, 185, 129, 0.1)';
                stateText.style.color = '#10b981';
            } else {
                card.classList.remove('charging');
                stateText.style.background = 'rgba(255, 255, 255, 0.05)';
                stateText.style.color = '#94a3b8';
            }
        }
    }
});

function sendCmd(id, action) {
    socket.emit('ui_command', { id, action });
}
