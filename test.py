def top_n_entries(entries, n):
    """
    Returns the top N entries from a list of dictionaries sorted by score descending.

    Parameters:
    entries (list of dict): Each dict must have 'name' and 'score' keys.
    n (int): Number of top entries to return.

    Returns:
    list of dict: Top N entries sorted by score descending.
    """
    if not isinstance(entries, list):
        raise TypeError("Entries must be a list")

    # Handle case where n is larger than list length
    n = min(n, len(entries))

    # Sort by score descending
    sorted_entries = sorted(entries, key=lambda x: x['score'], reverse=True)

    # Return top n
    return sorted_entries[:n]

data = [
    {'name': 'Alice', 'score': 85},
    {'name': 'Bob', 'score': 92},
    {'name': 'Charlie', 'score': 78},
    {'name': 'Diana', 'score': 95}
]

print(top_n_entries(data, 2))
# Output: [{'name': 'Diana', 'score': 95}, {'name': 'Bob', 'score': 92}]

print(top_n_entries(data, 10))  # n larger than list length -> returns all
# Output: all 4 entries sorted descending