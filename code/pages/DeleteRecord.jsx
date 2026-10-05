import React, { useState } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";

function DeleteRecord({ onDelete, onDeleteRecord }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { id: paramId } = useParams(); 

  const initialId = paramId || location.state?.record || "";
  const [recordId, setRecordId] = useState(initialId);
  const [error, setError] = useState("");

  
  const handleDeleteFunc = onDelete || onDeleteRecord;

  const handleDelete = async (e) => {
    e.preventDefault();
    setError("");

    if (!recordId) {
      setError("Please provide a valid Record ID to delete.");
      return;
    }

    try {
      if (handleDeleteFunc) {
        await handleDeleteFunc(Number(recordId));
      } else {
        const response = await fetch(`http://localhost:8439/records/${recordId}`, {
          method: "DELETE", 
          credentials: "include",
        });

        if (response.status === 401) {
          throw new Error("Log in Required");
        }

        if (!response.ok) {
          const errBody = await response.json().catch(() => ({}));
          throw new Error(errBody.detail || "Unable to delete record");
        }

        navigate("/");
      }
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div>
      <h2>Delete Record</h2>
      <form onSubmit={handleDelete}>
        <div>
          <label htmlFor="delete-id">Record ID to Delete: </label>
          <input
            id="delete-id"
            type="number"
            value={recordId}
            onChange={(e) => setRecordId(e.target.value)}
            required
          />
        </div>
        <br />
        <p>
          Are you sure you want to delete{recordId}?
        </p>
        <button type="submit" style={{ backgroundColor: "red", color: "white" }}>
          Confirm Delete
        </button>
        <button
          type="button"
          onClick={() => navigate("/")}
          style={{ marginLeft: "10px" }}
        >
          Cancel
        </button>
      </form>
    </div>
  );
}

export default DeleteRecord;