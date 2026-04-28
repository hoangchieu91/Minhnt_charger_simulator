#!/bin/bash

# Configuration
PI_IP="10.25.7.60"
PI_USER="pi"
PI_PASS="Raspberry"
REMOTE_DIR="/home/pi/Minhnt_charger_simulator"

echo "🚀 Starting Deployment to Raspberry Pi ($PI_IP)..."

# Create remote directory
sshpass -p "$PI_PASS" ssh -o StrictHostKeyChecking=no $PI_USER@$PI_IP "mkdir -p $REMOTE_DIR/web"

# Sync files
echo "📦 Syncing files..."
sshpass -p "$PI_PASS" scp unified_simulator.py $PI_USER@$PI_IP:$REMOTE_DIR/
sshpass -p "$PI_PASS" scp web/index.html web/style.css web/script.js $PI_USER@$PI_IP:$REMOTE_DIR/web/

# Install dependencies and setup systemd
echo "⚙️ Setting up dependencies and service..."
sshpass -p "$PI_PASS" ssh $PI_USER@$PI_IP << EOF
    sudo apt-get update
    sudo apt-get install -y python3-pip python3-flask python3-flask-socketio python3-pymodbus python3-serial
    
    # Create systemd service
    sudo bash -c 'cat > /etc/systemd/system/charger-sim.service << SERVICE
[Unit]
Description=Minhnt Charger and Meter Simulator
After=network.target

[Service]
ExecStart=/usr/bin/python3 $REMOTE_DIR/unified_simulator.py
WorkingDirectory=$REMOTE_DIR
StandardOutput=inherit
StandardError=inherit
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
SERVICE'

    sudo systemctl daemon-reload
    sudo systemctl enable charger-sim.service
    sudo systemctl restart charger-sim.service
EOF

echo "✅ Deployment complete! Dashboard: http://$PI_IP:5000"
