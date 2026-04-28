import paramiko
import re

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.25.7.116", username="user", password="Admin@12345")

stdin, stdout, stderr = ssh.exec_command("cat /etc/nginx/sites-available/nxchieu.duckdns.org.conf")
conf = stdout.read().decode()

pattern = r"(?s)location /master/ \{.*?\n    \}"

new_master = """location /master/ {
        proxy_pass http://10.25.7.142:80/;
        proxy_set_header Host $host;
        proxy_set_header Accept-Encoding ""; 
        sub_filter '="/' '="/master/';
        sub_filter "='/" "='/master/";
        sub_filter "open('POST', '/" "open('POST', '/master/";
        sub_filter "open('GET', '/" "open('GET', '/master/";
        sub_filter "fetch('/" "fetch('/master/";
        sub_filter_once off;

        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
        proxy_pass_header Authorization;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }"""

if re.search(pattern, conf):
    new_conf = re.sub(pattern, new_master, conf)
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/nxchieu.duckdns.org.conf", "w") as f:
        f.write(new_conf)
    sftp.close()

    commands = [
        "echo 'Admin@12345' | sudo -S cp /tmp/nxchieu.duckdns.org.conf /etc/nginx/sites-available/nxchieu.duckdns.org.conf",
        "echo 'Admin@12345' | sudo -S ln -sf /etc/nginx/sites-available/nxchieu.duckdns.org.conf /etc/nginx/sites-enabled/nxchieu.duckdns.org.conf",
        "echo 'Admin@12345' | sudo -S systemctl reload nginx"
    ]
    for cmd in commands:
        ssh.exec_command(cmd)
    print("Patch applied via Regex!")
else:
    print("Error: Could not find /master/ block using regex.")

ssh.close()
