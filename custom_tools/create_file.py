from langchain_core.tools import tool

@tool
def create_file(file_path: str, content: str) -> str:
    """
    Create and write content to a file on the local filesystem.

    :param file_path: The full path where the file should be created.
    :param content: The string content to write into the file.
    :return: A success message or an error if the operation fails.
    """
    try:
        with open(file_path, 'w') as file:
            file.write(content)
        return f"File created and written at {file_path}"
    except Exception as e:
        return f"Error: Failed to create file - {str(e)}"
