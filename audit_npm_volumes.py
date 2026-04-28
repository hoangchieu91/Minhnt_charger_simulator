import paramiko

def audit_npm(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        # 1. Find NPM volumes
        print("--- Docker Volume Inspection (NPM) ---")
        cmd = "docker inspect npm --format '{{ range .Mounts }}{{ .Source }}:{{ .Destination }}\n{{ end }}' 2>/dev/null"
        stdin, stdout, stderr = client.exec_command(cmd)
        mounts = stdout.read().decode().strip()
        print(mounts)
        
        # 2. Search for DuckDNS config in those volumes
        # Typically NPM maps /data to a local dir.
        data_mount = ""
        for line in mounts.splitlines():
            if ":/data" in line:
                data_mount = line.split(":")[0]
                break
        
        if data_mount:
            print(f"\nSearching in NPM Data Mount: {data_mount}")
            search_cmd = f"grep -r 'nxchieu.duckdns.org' {data_mount}/nginx/proxy_host 2>/dev/null"
            stdin, stdout, stderr = client.exec_command(search_cmd)
            results = stdout.read().decode()
            print(results)
            
            for line in results.splitlines():
                if ".conf:" in line:
                    conf_file = line.split(":")[0]
                    print(f"\n--- Content of {conf_file} ---")
                    _, so, _ = client.exec_command(f"cat {conf_file}")
                    print(so.read().decode())
        else:
            print("\nNPM data mount not found. Searching globally...")
            client.exec_command("grep -r 'nxchieu.duckdns.org' / 2>/dev/null | grep '.conf:'")
            # This might be too slow, so skip for now.
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    audit_npm("10.25.7.116", "user", "Admin@12345")
