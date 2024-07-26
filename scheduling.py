from google.oauth2 import service_account
import google.auth.transport.requests
import requests
import json
def solve_shift_scheduling(request_data):
    # Set up credentials
    credentials = service_account.Credentials.from_service_account_file(
        'credentials.json',
        scopes=['https://www.googleapis.com/auth/cloud-platform']
    )

    # Create authorized session
    authed_session = google.auth.transport.requests.AuthorizedSession(credentials)

    # API endpoint
    url = "https://optimization.googleapis.com/v1/scheduling:solveShiftScheduling"

    # Send request
    response = authed_session.post(url, json=request_data)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
        return None

# Load the request data
with open('shift_scheduling_request.json', 'r') as f:
    request_data = json.load(f)

# Solve the scheduling problem
solution = solve_shift_scheduling(request_data)

if solution:
    # Process and display the solution
    for assignment in solution.get('assignments', []):
        print(f"Employee: {assignment['employee_id']}, Shift: {assignment['shift_id']}")
else:
    print("Failed to find a solution.")