import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.25.7.116", username="user", password="Admin@12345")
stdin, stdout, stderr = ssh.exec_command("ls -la /etc/nginx/sites-available/")
print(stdout.read().decode())
