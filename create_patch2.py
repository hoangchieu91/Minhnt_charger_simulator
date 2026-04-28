import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("10.25.7.116", username="user", password="Admin@12345")

stdin, stdout, stderr = ssh.exec_command("cat /etc/nginx/sites-available/nxchieu.duckdns.org.conf")
conf = stdout.read().decode()

old_master = """    location /master/ {
        proxy_pass http://10.25.7.142:80/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
        proxy_pass_header Authorization;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }"""

new_master = """    location /master/ {
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

if old_master in conf:
    new_conf = conf.replace(old_master, new_master)
    # create a bash script to overwrite the file cleanly with sudo
    with open("patch_nginx2.sh", "w", encoding='utf8') as f:
        f.write("#!/bin/bash\n")
        f.write("cat << 'EOF' > /tmp/nx_new.conf\n")
        f.write(new_conf)
        f.write("\nEOF\n")
        f.write("echo 'Admin@12345' | sudo -S cp /tmp/nx_new.conf /etc/nginx/sites-available/nxchieu.duckdns.org.conf\n")
        f.write("echo 'Admin@12345' | sudo -S ln -sf /etc/nginx/sites-available/nxchieu.duckdns.org.conf /etc/nginx/sites-enabled/nxchieu.duckdns.org.conf\n")
        f.write("echo 'Admin@12345' | sudo -S systemctl reload nginx\n")
    print("Created local patch script.")
else:
    print("Error: Could not find exact location /master/ block in config.")

ssh.close()
