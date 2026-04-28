import paramiko

def read_configs(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        # Determine if it's NPM (Nginx Proxy Manager)
        stdin, stdout, stderr = client.exec_command("ls -d /data/nginx/proxy_host 2>/dev/null")
        is_npm = stdout.read().decode().strip() == "/data/nginx/proxy_host"
        
        if is_npm:
            print("Detected Nginx Proxy Manager (NPM)")
            cmd = "grep -l 'nxchieu.duckdns.org' /data/nginx/proxy_host/*.conf 2>/dev/null"
            stdin, stdout, stderr = client.exec_command(cmd)
            files = stdout.read().decode().splitlines()
            for f in files:
                print(f"\n--- Content of {f} ---")
                _, so, _ = client.exec_command(f"cat {f}")
                print(so.read().decode())
        else:
            print("Standard Nginx detected")
            cmd = "grep -l 'nxchieu.duckdns.org' /etc/nginx/conf.d/*.conf 2>/dev/null"
            stdin, stdout, stderr = client.exec_command(cmd)
            files = stdout.read().decode().splitlines()
            for f in files:
                print(f"\n--- Content of {f} ---")
                _, so, _ = client.exec_command(f"cat {f}")
                print(so.read().decode())
                
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    read_configs("10.25.7.116", "user", "Admin@12345")
