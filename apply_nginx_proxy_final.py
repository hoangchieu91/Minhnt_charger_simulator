import paramiko
import re

def update_nginx_final(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        fpath = "/etc/nginx/sites-enabled/nxchieu.duckdns.org.conf"
        print(f"Reading active config: {fpath}")
        _, content_out, _ = client.exec_command(f"cat {fpath}")
        original_content = content_out.read().decode()
        
        if not original_content:
            print("Error: Could not read config file content.")
            return

        # 2. Backup on remote
        client.exec_command(f"cp {fpath} {fpath}.bak")
        
        # 3. Modify content
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
        # Better regex to match 'location / { ... }' precisely
        pattern = r"location / \{[\s\S]*?\n    \}"
        if re.search(pattern, new_content):
            new_content = re.sub(pattern, slave_loc + "\n" + master_loc, new_content)
        else:
            # If no root location found, find the last } of the server block and prepend
            pos = new_content.rfind("}")
            new_content = new_content[:pos] + "\n" + slave_loc + "\n" + master_loc + "\n" + new_content[pos:]

        # 4. Write back via temporary file to ensure permissions if needed, but here simple write
        print("Writing new configuration...")
        sftp = client.open_sftp()
        with sftp.file(fpath, 'w') as f:
            f.write(new_content)
        sftp.close()
            
        # 5. Test and Reload
        print("Testing Nginx configuration...")
        _, so, se = client.exec_command("nginx -t")
        res = se.read().decode()
        print(res)
        if "syntax is ok" in res:
            print("Reloading Nginx...")
            client.exec_command("systemctl reload nginx")
            print("SUCCESS")
        else:
            print("ERROR: Nginx syntax check failed. Rolling back.")
            client.exec_command(f"cp {fpath}.bak {fpath}")
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    update_nginx_final("10.25.7.116", "user", "Admin@12345")
