import pandas as pd
import re

def split_header_body(content_lines):
    """
    Splits the content of a file into HEADER and BODY sections.
    Args:
        content_lines (list): List of lines in the file.
    Returns:
        tuple: HEADER and BODY sections as lists of strings.
    """
    # Limpia las líneas antes de buscar
    content_cleaned = [line.strip() for line in content_lines if line.strip()]
    
    try:
        header_start = content_cleaned.index("HEADER")
        body_start = content_cleaned.index("BODY")
    except ValueError:
        print("Content does not contain 'HEADER' or 'BODY'. Debugging content:")
        # print(content_cleaned)  # Imprime el contenido para depuración
        raise ValueError("The file does not contain expected HEADER or BODY sections.")
    
    header = content_cleaned[header_start + 1 : body_start] # splits the information for header dataset
    body = content_cleaned[body_start + 1 :] # splits the information for body dataset
    
    return header, body

def process_header(header):
    """
    Processes the HEADER section and extracts relevant fields.
    Args:
        header (list): List of lines in the HEADER section.
    Returns:
        dict: Extracted data from the HEADER section.
    """
    # Regular expressions for extract specific information in header
    try:
        numero_sorteo = re.search(r"NO. (\d+)", header[0]).group(1)
        tipo_sorteo = re.search(r"SORTEO (\w+)", header[0], re.IGNORECASE).group(1)
        fecha_sorteo = re.search(r"FECHA DEL SORTEO: ([\d/]+)", " ".join(header)).group(1)
        fecha_caducidad = re.search(r"FECHA DE CADUCIDAD: ([\d/]+)", " ".join(header)).group(1)
        premios = re.search(r"PRIMER PREMIO (\d+) \|\|\| SEGUNDO PREMIO (\d+) \|\|\| TERCER PREMIO (\d+)", " ".join(header))
        primer_premio, segundo_premio, tercer_premio = premios.groups()
        reintegros = re.search(r"REINTEGROS ([\d, ]+)", " ".join(header)).group(1).replace(" ", "")
    except AttributeError as e:
        print("An error occurred while processing the HEADER.")
        raise ValueError("The HEADER does not contain the expected format.") from e
    
    return {
        "numero_sorteo": int(numero_sorteo),
        "tipo_sorteo": tipo_sorteo,
        "fecha_sorteo": fecha_sorteo,
        "fecha_caducidad": fecha_caducidad,
        "primer_premio": int(primer_premio),
        "segundo_premio": int(segundo_premio),
        "tercer_premio": int(tercer_premio),
        "reintegros": reintegros
    }
    
def process_body(body):
    """
    Processes the BODY section and extracts relevant fields.
    Args:
        body (list): List of lines in the BODY section.
    Returns:
        list: List of dictionaries with processed premios data, including reintegros.
    """
    premios_data = []
    last_premio_index = None  # Índice del último premio procesado

    print("Processing BODY:")  # Que hace este codigo? 
    for line in body:
        line = line.strip()
        if not line:
            continue

        print(f"Processing line: {line}")
        
        # Intentar coincidir con una línea de premio
        match = re.match(r"(\d+)\s+(\w+)\s+\.+\s+([\d,]+\.?\d*)", line)
        if match:
            numero_premiado, letras, monto = match.groups()
            monto = float(monto.replace(",", ""))  # Limpiar el monto
            # reintegro = int(numero_premiado[-1]) # Extract the last digit
            
            premios_data.append({
                "numero_premiado": numero_premiado,
                "letras": letras,
                "monto": monto,
                # "reintegro": reintegro, # Add reintegro column
                "vendido_por": None,  # Default Value to None
                "ciudad": None,       
                "departamento": None  
            })
            last_premio_index = len(premios_data) - 1  # Guarda el índice actual

        elif "VENDIDO POR" in line and last_premio_index is not None:
            # Si encontramos "VENDIDO POR", asignar al último premio
            current_vendedor = line.split("VENDIDO POR", 1)[1].strip()
            premios_data[last_premio_index]["vendido_por"] = current_vendedor

        elif "NO VENDIDO" in line and last_premio_index is not None:
            # Asignar "NO VENDIDO" con valores predeterminados
            premios_data[last_premio_index]["vendido_por"] = "NO VENDIDO" 
            premios_data[last_premio_index]["ciudad"] = None # Adding "None" for compatilibility with SQL 
            premios_data[last_premio_index]["departamento"] = None

        else:
            # Ignorar las líneas que no coinciden (para depuración)
            print(f"Ignored line: {line}")

    print(f"Premios processed: {len(premios_data)}")
    return premios_data

def split_vendido_por_column(df):
    """
    Splits the 'vendido_por' column into 'vendedor', 'ciudad', and 'departamento'.
    Args:
        df (pd.DataFrame): DataFrame with 'vendido_por' column.
    Returns:
        pd.DataFrame: DataFrame with new columns and 'vendido_por' removed.
    """
    split_data = df['vendido_por'].str.split(r',', expand=True) # separates the info by using ","
    df['vendedor'] = split_data[0].str.strip()  # Extract vendor name
    df['ciudad'] = split_data[1].str.strip() if split_data.shape[1] > 1 else None  # Extract city
    df['departamento'] = split_data[2].str.strip() if split_data.shape[1] > 2 else None  # Extract department
    df.drop(columns=['vendido_por'], inplace=True)  # Remove original column
    return df