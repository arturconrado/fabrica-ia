def markdown_table(headers, rows):
    header = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join(["---"] * len(headers)) + " |"
    body = ["| " + " | ".join(map(str, row)) + " |" for row in rows]
    return "\n".join([header, sep] + body)
