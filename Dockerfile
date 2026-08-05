# Use a small, official Python image
FROM python:3.11-slim

# Set working directory inside the container
WORKDIR /app

# LaTeX engine needed to compile exported exam papers into PDF
# (latex_export.py shells out to pdflatex/xelatex). booklet.cls only needs
# geometry, amsmath, amssymb, enumitem, xcolor and framed, which these
# three package groups cover -- no need for the multi-GB texlive-full.
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency list first (better build caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the project (app.py, pages/, etc.)
COPY . .

# NiceGUI's default port
EXPOSE 8080

# Run the app
CMD ["python", "app.py"]
