#!/usr/bin/env python3
import os
import sys
import subprocess
import fnmatch
from typing import List, Tuple

CACHE_FILES = [
    "*.pyc",
    "*.class",
    "*.o",
    "*.obj",
    "*.dll",
    "*.exe",
    "*.so",
    "*.cache",
    "*.swp",
    "*~",
]

CACHE_DIRS = [
    "__pycache__",
    "node_modules",
    "target",
    "build",
    "dist",
    ".cache",
    ".pytest_cache",
    "*.egg-info",
    "vendor",
    ".gradle",
]

SKIP_FILES = [
    "__init__.py",
    "aider-cli.py",
    "aider-cli.sh",
    ".aider.chat.history.md",
    ".aider.conf.yml",
    ".aider.input..aider.input.history",
    ".aider.tags..aider.tags.cache.v3/",
    ".codeiumignore",
    "README.md",
    "ARCHITECTURE.md"
] + CACHE_FILES

SKIP_DIRS = [
    ".git/",
    "config/",
    "docs/",
    "input/",
    "output/",
    "markdowns/"
] + CACHE_DIRS

FILE_TYPES = {
    '1': ('py', 'Python files'),
    '2': ('c', 'C files'),
    '3': ('cpp', 'C++ files'),
    '4': ('rs', 'Rust files'),
    '5': ('js', 'JavaScript files'),
    '6': ('ts', 'TypeScript files'),
    '7': ('sh', 'Shell scripts'),
    '8': (None, 'All files')
}

def get_git_files(file_type: str = None) -> List[str]:
    """
    Retrieve files from the Git repository.

    Args:
        file_type (str, optional): File extension to filter by.
                                   If None, retrieves all files.

    Returns:
        A sorted list of files and top-level directories.
    """
    try:
        cmd = ['git', 'ls-files', '--cached', '--others', '--exclude-standard']

        if file_type:
            cmd.append(f'*.{file_type}')

        files = subprocess.check_output(cmd, text=True).splitlines()

        top_dirs = set()
        for file in files:
            parts = file.split('/')
            if len(parts) > 1:
                top_dirs.add(f"{parts[0]}/")

        all_entries = sorted(list(top_dirs) + files, key=lambda x: (not x.endswith('/'), x.lower()))

        return all_entries
    except subprocess.CalledProcessError as e:
        print(f"Error retrieving Git files: {e}", file=sys.stderr)
        sys.exit(1)

def filter_files(files: List[str], skip_patterns: List[str], skip_dirs: List[str]) -> List[str]:
    """Filter out files matching skip patterns."""
    def should_keep(file: str) -> bool:
        if file.endswith('/'):
            for dir in skip_dirs:
                if file.startswith(dir):
                    return False
            return True

        if os.path.basename(file).startswith('.'):
            return False

        for pattern in skip_patterns:
            if fnmatch.fnmatch(os.path.basename(file), pattern):
                return False

        return True

    return [f for f in files if should_keep(f)]

def build_reload_command(is_back: bool = False) -> str:
    """Build the reload command for fzf ctrl+l binding."""
    dir_excludes = ' '.join(f"-not -path '*/{d}'" for d in CACHE_DIRS)
    file_excludes = ' '.join(f"-not -path '*/{f}'" for f in [f.replace('*', '**/') for f in CACHE_FILES])
    
    cmd = r'''cd {} && find . -maxdepth 1 \( -type d -o -type f \) {} {} -printf '%y %p\n' | sed 's|^d \.|0 {}|;s|^f \.|1 {}|' | sort | cut -d' ' -f2-'''
    if is_back:
        return r'''root=$(git rev-parse --show-toplevel 2>/dev/null || pwd) && cd "$root" && find . -maxdepth 1 \( -type d -o -type f \) ''' + dir_excludes + ' ' + file_excludes + r''' -printf '%y %p\n' | sed "s|^d \.|0 $(basename $(pwd))|;s|^f \.|1 $(basename $(pwd))|" | sort | cut -d' ' -f2-'''
    return cmd.format('{}', dir_excludes, file_excludes, '{}', '{}')

def interactive_file_selection(files: List[str]) -> List[str]:
    """Use fzf for interactive file selection with hierarchical directory support."""
    try:
        # Get initial directory from first file or use current directory
        current_dir = os.path.abspath(os.path.dirname(files[0]) if files else '.')
        # Get git root or use initial directory as the limit
        try:
            git_root = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip()
        except subprocess.CalledProcessError:
            git_root = current_dir

        fzf_input = '\n'.join(files)

        preview_cmd = '''
            if [ -d {} ]; then
                echo "Directory: {}";
                echo "Python files:";
                cd {} && find . -type f -name "*.py" -not -path "*/.*" -not -path "*/__pycache__/*" | sed 's|^./||' | sort | while read -r file; do
                    echo "  $file";
                    first_line=$(head -n 1 "$file" 2>/dev/null);
                    if [[ "$first_line" == "#!"* ]]; then
                        echo "    $first_line";
                    fi
                done;
            else
                echo "File: {}";
                bat --style=numbers --color=always {} 2>/dev/null || cat {};
            fi
        '''

        fzf_command = [
            'fzf',
            '--multi',
            '--preview', preview_cmd,
            '--preview-window', 'right:60%',
            '--bind', 'ctrl-p:toggle-preview',
            '--bind', f'ctrl-l:reload({build_reload_command()})',
            '--bind', f'ctrl-k:reload(echo "{fzf_input}")',
            '--bind', f'right:reload({build_reload_command()})',
            '--bind', f'left:reload(echo "{fzf_input}")',
            '--header', 'Select files and directories (TAB to multi-select, →/CTRL+L to expand, ←/CTRL+K to go back)',
            '--layout', 'reverse',
            '--height', '80%',
            '--ansi'
        ]

        result = subprocess.run(
            fzf_command,
            input=fzf_input.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        if result.returncode == 0:
            selected = result.stdout.decode().strip().split('\n')
            final_files = []
            for item in selected:
                if os.path.isdir(item):
                    # If directory is selected, add all Python files in it recursively
                    for root, _, filenames in os.walk(item):
                        for filename in filenames:
                            if filename.endswith('.py'):
                                abs_path = os.path.join(root, filename)
                                rel_path = os.path.relpath(abs_path, git_root)
                                final_files.append(rel_path)
                else:
                    # If file is selected, add it with relative path
                    rel_path = os.path.relpath(item, git_root)
                    final_files.append(rel_path)
            return sorted(set(final_files))  # Remove duplicates
        return []
    except Exception as e:
        print(f"Error running fzf: {e}", file=sys.stderr)
        sys.exit(1)

def sort_files(files: List[str]) -> List[str]:
    """
    Sort files with directories prioritized at every level.

    Args:
        files (List[str]): List of files and directories to sort.

    Returns:
        List[str]: Sorted list of files and directories.
    """
    def file_key(file: str) -> Tuple[int, bool, str, str]:
        parts = file.split('/')
        is_dir = file.endswith('/')

        return (
            len(parts),
            not is_dir,
            ''.join(p + '/' for p in parts[:-1]),
            parts[-1].lower()
        )

    return sorted(files, key=file_key)

def expand_directory(directory: str) -> List[str]:
    """Expand a directory to all files within it."""
    try:
        cmd = ['git', 'ls-files', '--cached', '--others', '--exclude-standard', f'{directory}*']
        return subprocess.check_output(cmd, text=True).splitlines()
    except subprocess.CalledProcessError:
        print(f"Error finding files in {directory}", file=sys.stderr)
        return []

def main():
    print("Select file type to list:")
    for key, (ext, description) in FILE_TYPES.items():
        print(f"{key}. {description}")

    while True:
        choice = input("Enter your choice (1-8): ").strip()
        if choice in FILE_TYPES:
            break
        print("Invalid choice. Please try again.")

    selected_type, description = FILE_TYPES[choice]
    print(f"Listing {description}")

    all_files = get_git_files(selected_type)

    filtered_files = filter_files(all_files, SKIP_FILES, SKIP_DIRS)

    sorted_files = sort_files(filtered_files)

    selected_files = interactive_file_selection(sorted_files)

    final_files = []
    for file in selected_files:
        if file.endswith('/'):
            final_files.extend(expand_directory(file))
        else:
            final_files.append(file)

    if not final_files:
        print("No files selected. Exiting.")
        sys.exit(0)

    # Build aider command with properly formatted file arguments
    aider_command = ["aider"]
    for f in final_files:
        aider_command.extend(["--file", f])

    print("Generated Aider command:")
    print(' '.join(aider_command))

    execute = input("Do you want to execute this command? (yes/no): ").lower()
    if execute == 'yes':
        subprocess.run(aider_command)

if __name__ == '__main__':
    main()
