import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.25.7.116", username="user", password="Admin@12345")

sftp = ssh.open_sftp()
sftp.put("ngx.conf", "/tmp/ngx.conf")
sftp.close()

commands = [
    "echo 'Admin@12345' | sudo -S cp /tmp/ngx.conf /etc/nginx/sites-available/nxchieu.duckdns.org.conf",
    "echo 'Admin@12345' | sudo -S ln -sf /etc/nginx/sites-available/nxchieu.duckdns.org.conf /etc/nginx/sites-enabled/nxchieu.duckdns.org.conf",
    "echo 'Admin@12345' | sudo -S nginx -t",
    "echo 'Admin@12345' | sudo -S systemctl reload nginx"
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print("STDOUT:", stdout.read().decode())
    print("STDERR:", stderr.read().decode())

ssh.close()
