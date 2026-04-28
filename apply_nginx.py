import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.25.7.116", username="user", password="Admin@12345")

# Upload
sftp = ssh.open_sftp()
sftp.put("nxchieu.duckdns.org.conf", "/tmp/nxchieu.duckdns.org.conf")
sftp.close()

# Move and Reload
commands = [
    "echo 'Admin@12345' | sudo -S cp /tmp/nxchieu.duckdns.org.conf /etc/nginx/sites-enabled/nxchieu.duckdns.org.conf",
    "echo 'Admin@12345' | sudo -S nginx -t",
    "echo 'Admin@12345' | sudo -S systemctl reload nginx"
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print(stdout.read().decode())
    print(stderr.read().decode())

ssh.close()
