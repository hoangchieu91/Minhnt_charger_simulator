import paramiko
import re
import os

def update_nginx_sudo_v2(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        fpath = "/etc/nginx/sites-enabled/nxchieu.duckdns.org.conf"
        print(f"Reading active config: {fpath}")
        _, content_out, _ = client.exec_command(f"cat {fpath}")
        # Use utf-8 for decoding remote content
        original_content = content_out.read().decode('utf-8', 'ignore')
        
        if not original_content:
            print("Error: Could not read config file content.")
            return

        # 2. Modify content
        slave_loc = """    location /slave/ {
        proxy_pass http://10.25.7.111:5000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
"""
        master_loc = """    location /master/ {
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
    }
"""
        
        new_content = original_content
        pattern = r"location / \{[\s\S]*?\n    \}"
        if re.search(pattern, new_content):
            new_content = re.sub(pattern, slave_loc + "\n" + master_loc, new_content)
        else:
            pos = new_content.rfind("}")
            new_content = new_content[:pos] + "\n" + slave_loc + "\n" + master_loc + "\n" + new_content[pos:]

        # 3. Write locally to a temp file WITH UTF-8
        temp_local = "nginx_temp_v2.conf"
        with open(temp_local, 'w', encoding='utf-8') as f:
            f.write(new_content)

        # 4. Upload to /tmp
        print("Uploading to /tmp/nxchieu.conf...")
        sftp = client.open_sftp()
        sftp.put(temp_local, "/tmp/nxchieu.conf")
        sftp.close()
        os.remove(temp_local)
            
        # 5. Move and Reload with SUDO
        print("Applying config with sudo...")
        sudo_cmd = f"echo '{password}' | sudo -S mv /tmp/nxchieu.conf {fpath}"
        stdin, stdout, stderr = client.exec_command(sudo_cmd)
        print(stderr.read().decode())
        
        print("Testing Nginx configuration...")
        stdin, stdout, stderr = client.exec_command(f"echo '{password}' | sudo -S nginx -t")
        res = stderr.read().decode()
        print(res)
        
        if "syntax is ok" in res:
            print("Reloading Nginx...")
            client.exec_command(f"echo '{password}' | sudo -S systemctl reload nginx")
            print("SUCCESS")
        else:
            print("ERROR: Nginx syntax check failed. Please check /tmp/nxchieu.conf.")
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    update_nginx_sudo_v2("10.25.7.116", "user", "Admin@12345")
