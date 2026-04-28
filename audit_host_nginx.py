import paramiko

def audit_host_nginx(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        # 1. Check if Nginx is a system service
        print("--- Nginx System Service ---")
        _, so, _ = client.exec_command("systemctl is-active nginx")
        print(f"Status: {so.read().decode().strip()}")
        
        # 2. Find config files in /etc/nginx/sites-enabled
        print("\n--- Nginx Sites Enabled ---")
        _, so, _ = client.exec_command("ls -l /etc/nginx/sites-enabled/ 2>/dev/null")
        print(so.read().decode())
        
        # 3. Read the site for nxchieu.duckdns.org
        print("\n--- Searching for Active DuckDNS Config ---")
        find_cmd = "grep -r 'nxchieu.duckdns.org' /etc/nginx/ 2>/dev/null"
        _, so, _ = client.exec_command(find_cmd)
        results = so.read().decode()
        print(results)
        
        for line in results.splitlines():
            if ":" in line:
                fpath = line.split(":")[0]
                if fpath.endswith(".conf") or "sites-enabled" in fpath:
                    print(f"\n--- Content of {fpath} ---")
                    _, content, _ = client.exec_command(f"cat {fpath}")
                    print(content.read().decode())
                    
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    audit_host_nginx("10.25.7.116", "user", "Admin@12345")
