import paramiko

def inspect_conf(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        files = ["/etc/nginx/sites-enabled/frps_secure.conf", "/etc/nginx/sites-enabled/nxchieu.duckdns.org.conf"]
        for f in files:
            print(f"\n--- Reading {f} ---")
            _, so, _ = client.exec_command(f"cat {f}")
            print(so.read().decode())
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    inspect_conf("10.25.7.116", "user", "Admin@12345")
