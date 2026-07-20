# Use a small, official Python image
FROM python:3.11-slim

# Set working directory inside the container
WORKDIR /app

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
