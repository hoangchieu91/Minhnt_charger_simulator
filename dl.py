import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.25.7.116", username="user", password="Admin@12345")
sftp = ssh.open_sftp()
sftp.get("/etc/nginx/sites-available/nxchieu.duckdns.org.conf", "ngx.conf")
sftp.close()
ssh.close()
