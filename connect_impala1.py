import os
import pyodbc
import time
import sys
import traceback

# Tracks the most recent execute_query() failure reason
_last_error = None

def get_last_error():
    """Return the human-readable reason the last execute_query() call failed."""
    return _last_error

def extract_pwd(dl_con_path, key):
    """Extract password or IP from config file."""
    try:
        with open(dl_con_path, 'r') as f:
            for line in f:
                line = line.strip()
                if key == "p" and line.startswith('PWD='):
                    return line.split('=', 1)[1].strip()
                elif key == "u" and line.startswith('UID='):
                    return line.split('=', 1)[1].strip() 
                elif key == "h" and line.startswith('HOST='):
                    return line.split('=', 1)[1].strip()
    except Exception as e:
        print(f"Error reading config file: {e}")
    return None

def test_impala_connection():
    """Test if Impala DSN connection is working."""
    global _last_error
    try:
        print("🔍 Testing Impala DSN connection...")
        conn = pyodbc.connect("DSN=impala_2;", autocommit=True, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 as test")
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        if result:
            print("✅ Impala DSN connection successful!")
            return True
        else:
            print("❌ Impala DSN connection failed - no result")
            _last_error = "Connection test failed - no result"
            return False
    except pyodbc.Error as e:
        error_msg = str(e)
        print(f"❌ Impala DSN connection error: {error_msg}")
        _last_error = f"Connection error: {error_msg}"
        return False
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Impala connection error: {error_msg}")
        _last_error = f"Connection error: {error_msg}"
        return False

def execute_query(query, project_path=None):
    """
    Execute a query against Impala using ODBC DSN.
    Returns (results, columns) for SELECT queries, or ("SUCCESS", None) for DDL/DML.
    """
    global _last_error
    conn = None
    cursor = None
    
    # Retry configuration
    max_retries = 3
    retry_delay = 5
    last_exception = None
    
    # Clear previous error
    _last_error = None
    
    for attempt in range(max_retries):
        try:
            print(f"  [Attempt {attempt + 1}/{max_retries}] Connecting to Impala...")
            
            # Connect with timeout
            conn = pyodbc.connect("DSN=impala_2;", autocommit=True, timeout=30)
            cursor = conn.cursor()
            
            # Print the query for debugging (truncated)
            query_preview = query[:200] + "..." if len(query) > 200 else query
            print(f"  Executing: {query_preview}")
            
            # Execute query
            start_time = time.time()
            cursor.execute(query)
            execution_time = time.time() - start_time
            print(f"  Query executed in {execution_time:.2f} seconds")
            
            # For SELECT and DESCRIBE queries, fetch results
            query_upper = query.strip().upper()
            if query_upper.startswith("SELECT") or query_upper.startswith("DESCRIBE") or query_upper.startswith("SHOW"):
                # Get column names
                columns = [desc[0] for desc in cursor.description]
                if not columns:
                    print("  ⚠️ No columns returned")
                    return None, None
                
                print(f"  Columns ({len(columns)}): {columns[:5]}{'...' if len(columns) > 5 else ''}")
                
                # Fetch results in chunks
                results = []
                while True:
                    batch = cursor.fetchmany(10000)
                    if not batch:
                        break
                    # Convert pyodbc.Row -> plain tuple. pyodbc.Row supports
                    # len()/indexing so callers' "len(columns)==len(row)"
                    # checks pass, but handing a list of Row objects straight
                    # to pd.DataFrame(...) can make pandas/numpy collapse each
                    # row into a single opaque object instead of expanding it
                    # into N columns — producing errors like
                    # "Shape of passed values is (N, 1), indices imply (N, 7)".
                    # Plain tuples avoid that ambiguity entirely.
                    results.extend(tuple(row) for row in batch)
                    del batch
                
                print(f"  ✅ Query successful - {len(results)} rows returned")
                return results, columns
            else:
                # For non-SELECT queries
                affected_rows = cursor.rowcount
                print(f"  ✅ Query executed successfully - {affected_rows} rows affected")
                return "SUCCESS", None

        except pyodbc.Error as e:
            error_str = str(e)
            last_exception = e
            print(f"  ⚠️ pyodbc Error (attempt {attempt + 1}): {error_str}")
            
            # Check if it's a retryable error
            is_retryable = (
                '08S01' in error_str or 
                'timeout' in error_str.lower() or 
                'timed out' in error_str.lower() or
                'SSL' in error_str or
                'connection' in error_str.lower() or
                'could not connect' in error_str.lower()
            )
            
            if is_retryable and attempt < max_retries - 1:
                print(f"  🔄 Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                # Not retryable or max retries exceeded
                _last_error = f"ODBC Error: {error_str}"
                print(f"  ❌ ODBC Error: {error_str}")
                
                # Check for specific error types
                if 'AnalysisException' in error_str:
                    if 'Could not resolve' in error_str or 'Table not found' in error_str:
                        _last_error = f"Table not found: {error_str}"
                    elif 'AuthorizationException' in error_str:
                        _last_error = f"Authorization error: {error_str}"
                    else:
                        _last_error = f"Analysis error: {error_str}"
                elif 'HY000' in error_str:
                    if 'timeout' in error_str.lower():
                        _last_error = f"Query timeout: {error_str}"
                    else:
                        _last_error = f"General error (HY000): {error_str}"
                elif '08001' in error_str:
                    _last_error = f"Connection failed: {error_str}"
                
                return None, None

        except Exception as e:
            error_str = str(e)
            print(f"  ❌ Unexpected error (attempt {attempt + 1}): {error_str}")
            traceback.print_exc()
            _last_error = f"Unexpected error: {error_str}"
            return None, None

        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass
            if conn:
                try:
                    conn.close()
                except:
                    pass
    
    # If we exhaust all retries
    print(f"  ❌ All {max_retries} attempts failed")
    _last_error = f"All {max_retries} attempts failed: {last_exception}"
    return None, None

# ──────────────────── Hive connections (kept for reference) ────────────────────
from pyhive import hive

def execute_hive_query(query, project_path):
    """
    Execute a query against Hive using pyhive.
    """
    pwd = extract_pwd(os.path.join(project_path, "DL_221.txt"), "p")
    username = extract_pwd(os.path.join(project_path, "DL_221.txt"), "u")
    host_ip = extract_pwd(os.path.join(project_path, "DL_221.txt"), "h")

    if not pwd or not host_ip:
        print("Password or Host IP not found in config file.")
        return None, None

    conn = None
    cursor = None

    max_retries = 3
    retry_delay = 5
    last_exception = None

    for attempt in range(max_retries):
        try:
            print(f"Attempt {attempt + 1} of {max_retries} to execute Hive query...")

            conn = hive.Connection(
                host=host_ip,
                port=10000,
                username=username,
                password=pwd,
                auth='CUSTOM',
                database='default',
                ssl=True,
                configuration={'hive.server2.ssl.truststore.path': 'D:\\ODBC_IMPALA\\ROOTHBL_v2.pem'}
            )

            cursor = conn.cursor()

            query_preview = query[:100] + "..." if len(query) > 100 else query
            print(f"Executing: {query_preview}")

            start_time = time.time()
            cursor.execute(query)
            execution_time = time.time() - start_time

            print(f"Query executed successfully in {execution_time:.2f} seconds")

            if query.strip().upper().startswith(("SELECT", "DESCRIBE")):
                columns = [desc[0] for desc in cursor.description]
                results = []
                while True:
                    batch = cursor.fetchmany(10000)
                    if not batch:
                        break
                    results.extend(tuple(row) for row in batch)
                    del batch
                print(f"SELECT/DESCRIBE successful - {len(results)} rows returned")
                return results, columns
            else:
                affected_rows = cursor.rowcount
                print(f"Query executed successfully - {affected_rows} rows affected")
                return "SUCCESS", None

        except Exception as e:
            print(f"Error (attempt {attempt + 1}): {e}")
            last_exception = e
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
            else:
                print("Max retries exceeded.")
                return None, None

        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    print(f"All {max_retries} attempts failed. Last error: {last_exception}")
    return None, None

# ──────────────────── Table helper functions ────────────────────

def table_exists(table_name, project_path):
    """
    Check if a table exists in the database.
    """
    try:
        # Extract schema and table name
        if '.' in table_name:
            schema, table = table_name.split('.')
        else:
            schema = 'fccm_uat'
            table = table_name
        
        table_lower = table.lower()
        schema_lower = schema.lower()
        
        print(f"Checking if table exists: {schema_lower}.{table_lower}")
        
        # Try SHOW TABLES instead of DESCRIBE (more reliable)
        show_query = f"SHOW TABLES IN {schema_lower} LIKE '{table_lower}'"
        result, columns = execute_query(show_query, project_path)
        
        if result is not None and len(result) > 0:
            print(f"✅ Table {table_name} exists")
            return True
        else:
            print(f"❌ Table {table_name} does not exist")
            return False
        
    except Exception as e:
        print(f"❌ Error checking if table {table_name} exists: {e}")
        return False

def table_has_records(table_name, project_path):
    """
    Check if a table has any records.
    """
    try:
        if not table_exists(table_name, project_path):
            print(f"Table {table_name} does not exist")
            return False
        
        # Count records in the table
        count_query = f"SELECT COUNT(*) as record_count FROM {table_name}"
        result, columns = execute_query(count_query, project_path)
        
        if result and len(result) > 0:
            record_count = result[0][0] if result[0] else 0
            has_records = record_count > 0
            print(f"Table {table_name} has {record_count} records")
            return has_records
        else:
            print(f"Could not determine record count for {table_name}")
            return False
            
    except Exception as e:
        print(f"Error checking records in table {table_name}: {e}")
        return False

def create_table_from_view(table_name, view_name, project_path, drop_if_exists=True):
    """
    Create a table from a view with comprehensive checks.
    """
    try:
        print(f"🔄 Processing: {table_name} from {view_name}")
        
        # Step 1: Check if source view exists
        print(f"   Checking if source view exists: {view_name}")
        if not table_exists(view_name, project_path):
            print(f"❌ Cannot create table - source view {view_name} does not exist")
            return False
        
        # Step 2: Check if target table exists
        print(f"   Checking if target table exists: {table_name}")
        table_already_exists = table_exists(table_name, project_path)
        
        if table_already_exists:
            if drop_if_exists:
                drop_query = f"DROP TABLE IF EXISTS {table_name}"
                print(f"   Dropping existing table: {drop_query}")
                result, _ = execute_query(drop_query, project_path)
                if result == "SUCCESS":
                    print(f"✅ Dropped existing table: {table_name}")
                else:
                    print(f"⚠️ Failed to drop table {table_name}, but continuing...")
            else:
                if table_has_records(table_name, project_path):
                    print(f"✅ Table {table_name} already exists and has records. Skipping creation.")
                    return True
                else:
                    print(f"ℹ️ Table {table_name} exists but is empty. Will recreate.")
                    drop_query = f"DROP TABLE IF EXISTS {table_name}"
                    execute_query(drop_query, project_path)
        
        # Step 3: Create table from view
        create_query = f"CREATE TABLE {table_name} STORED AS PARQUET AS SELECT * FROM {view_name}"
        print(f"   Creating table: {create_query}")
        result, _ = execute_query(create_query, project_path)
        
        if result != "SUCCESS":
            print(f"❌ Failed to create table {table_name}")
            return False
        
        # Compute stats
        compute_query = f"COMPUTE STATS {table_name}"
        print(f"   Computing stats: {compute_query}")
        execute_query(compute_query, project_path)
        
        # Step 4: Verify table was created
        if table_exists(table_name, project_path):
            print(f"✅ Successfully created table {table_name}")
            return True
        else:
            print(f"❌ Failed to create table {table_name}")
            return False
            
    except Exception as e:
        print(f"❌ Error creating table {table_name} from view {view_name}: {e}")
        return False

def load_hist_tables_from_file(file_path):
    """Load historical table mappings from file."""
    hist_tables = {}
    try:
        with open(file_path, 'r') as file:
            for line in file:
                if '=' in line:
                    key, value = line.strip().split('=', 1)
                    hist_tables[key.strip()] = value.strip()
    except Exception as e:
        print(f"Error loading hist tables from {file_path}: {str(e)}")
    return hist_tables

def backup_table(table_name, project_path, bk_suffix):
    """Backup table with cleaned suffix"""
    try:
        # First check if the table exists
        check_query = f"SHOW TABLES IN fccm_uat LIKE '{table_name}'"
        result, _ = execute_query(check_query, project_path)
        
        if result and len(result) > 0:
            full_table_name = f"FCCM_UAT.{table_name}"
            backup_name = f"{full_table_name}_{bk_suffix}"
            
            # Rename the table to the backup name
            backup_query = f"ALTER TABLE {full_table_name} RENAME TO {backup_name}"
            execute_query(backup_query, project_path)
            print(f"✅ Table {full_table_name} has been renamed to {backup_name}.")
        else:
            print(f"⚠️ Table {full_table_name} does not exist. Skipping backup.")
            
    except Exception as e:
        print(f"❌ Error backing up table {full_table_name}: {e}")

# ──────────────────── Connection test at module load ────────────────────

def test_connection_at_startup():
    """Test connection when module loads."""
    print("\n" + "="*50)
    print("Testing Impala DSN Connection...")
    print("="*50)
    
    if test_impala_connection():
        print("✅ Impala connection is ready.")
        return True
    else:
        print("❌ Impala connection failed. Please check:")
        print("  1. DSN 'impala_2' is configured in ODBC Data Sources")
        print("  2. Impala service is running")
        print("  3. Network connectivity to Impala server")
        print("  4. Credentials are correct")
        return False

# Run connection test when module is imported
# Uncomment the line below to test on import
# test_connection_at_startup()

# Example usage
if __name__ == "__main__":
    print("🔍 Testing connect_impala1.py...")
    
    # Test DSN connection
    if test_impala_connection():
        print("\n✅ Impala connection test passed!")
        
        # Test a simple query
        test_query = "SELECT 1 as test_value"
        result, columns = execute_query(test_query, None)
        if result is not None:
            print(f"✅ Test query successful: {result[:5]}")
            print(f"   Columns: {columns}")
        else:
            print(f"❌ Test query failed: {get_last_error()}")
    else:
        print("\n❌ Impala connection test failed!")
        print("Please check your DSN configuration for 'impala_2'.")
