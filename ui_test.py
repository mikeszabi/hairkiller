import cv2
import tkinter as tk
from PIL import Image, ImageTk

# Initialize the main tkinter window
root = tk.Tk()
root.title("Interactive Camera App with Buttons and Coordinates")

# Open the camera
cap = cv2.VideoCapture(2)  # Change the index if you have multiple cameras

# Variables to store the last clicked coordinates
clicked_x, clicked_y = None, None

# Create a canvas and add scrollbars
canvas = tk.Canvas(root, width=800, height=600)
scroll_x = tk.Scrollbar(root, orient="horizontal", command=canvas.xview)
scroll_y = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
canvas.configure(xscrollcommand=scroll_x.set, yscrollcommand=scroll_y.set)

scroll_x.pack(side="bottom", fill="x")
scroll_y.pack(side="right", fill="y")
canvas.pack(side="left", expand=True, fill="both")

# Create a frame inside the canvas
frame = tk.Frame(canvas)
canvas.create_window((0, 0), window=frame, anchor="nw")

# Function to update the video feed in tkinter window
def update_frame():
    global clicked_x, clicked_y
    ret, frame = cap.read()
    if ret:
        # If coordinates are set, draw them on the frame
        if clicked_x is not None and clicked_y is not None:
            # Draw a circle at the click point
            cv2.circle(frame, (clicked_x, clicked_y), 5, (0, 255, 0), -1)
            # Display the coordinates text
            cv2.putText(frame, f"({clicked_x}, {clicked_y})", 
                        (clicked_x + 10, clicked_y - 10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        
        # Convert the frame to an image for tkinter
        cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(cv2image)
        imgtk = ImageTk.PhotoImage(image=img)
        
        # Update the canvas image
        display.imgtk = imgtk
        display.config(image=imgtk)
        
        # Update the scroll region
        canvas.config(scrollregion=canvas.bbox("all"))
    
    # Schedule the next frame update
    root.after(10, update_frame)

# Mouse click event handler
def click_event(event):
    global clicked_x, clicked_y
    # Save the clicked coordinates
    clicked_x, clicked_y = event.x, event.y
    print(f"Clicked at (X: {clicked_x}, Y: {clicked_y})")

# Button event handler functions
def button_action_1():
    print("Button 1 pressed!")

def button_action_2():
    print("Button 2 pressed!")

# Create a label to display the video feed inside the frame
display = tk.Label(frame)
display.pack()
display.bind("<Button-1>", click_event)  # Bind left-click event

# Add buttons to the tkinter window
button1 = tk.Button(root, text="Button 1", command=button_action_1)
button1.pack(side=tk.LEFT, padx=10, pady=10)

button2 = tk.Button(root, text="Button 2", command=button_action_2)
button2.pack(side=tk.LEFT, padx=10, pady=10)

# Start the video update loop
update_frame()

# Run the tkinter main loop
root.mainloop()

# Release the camera when the window is closed
cap.release()
cv2.destroyAllWindows()