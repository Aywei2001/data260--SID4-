import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

function CreateRecord({ onAdd, onAddRecord, relatedEntities = [] }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  
  const [uniqueCode, setUniqueCode] = useState("");
  const [quantity, setQuantity] = useState(10);
  const [relatedEntityId, setRelatedEntityId] = useState(
    relatedEntities.length > 0 ? relatedEntities[0].id : ""
  );

  const [error, setError] = useState("");
  const navigate = useNavigate();

  const handleAdd = onAdd || onAddRecord;

  const handleSubmit = async (e) => {
    e.preventDefault(); 
    setError("");

    if (!relatedEntityId) {
      setError("Please select or create a Related Entity first.");
      return;
    }

    const newRecordData = {
      name,
      description,
      unique_code: uniqueCode,
      quantity: Number(quantity),
      related_entity_id: Number(relatedEntityId),
    };

    try {
      if (handleAdd) {
        await handleAdd(newRecordData);
      } else {
        const response = await fetch("http://localhost:8439/records", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(newRecordData),
        });

        if (response.status === 401) {
          throw new Error("Log in Required");
        }

        if (!response.ok) {
          const errBody = await response.json().catch(() => ({}));
          throw new Error(errBody.detail || "Unable to create record");
        }

        navigate("/");
      }
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h2>Add New Record</h2>

      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="name">Primary Field (Name): </label>
          <input
            id="name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="description">Secondary Field: </label>
          <input
            id="description"
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="uniqueCode">Unique Code: </label>
          <input
            id="uniqueCode"
            type="text"
            value={uniqueCode}
            onChange={(e) => setUniqueCode(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="quantity">Quantity: </label>
          <input
            id="quantity"
            type="number"
            min="0"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="relatedEntity">Related Entity: </label>
          <select
            id="relatedEntity"
            value={relatedEntityId}
            onChange={(e) => setRelatedEntityId(e.target.value)}
            required
          >
            {relatedEntities.length === 0 ? (
              <option value="">No Related Entities Available</option>
            ) : (
              relatedEntities.map((entity) => (
                <option key={entity.id} value={entity.id}>
                  {entity.primary_text} ({entity.code})
                </option>
              ))
            )}
          </select>
        </div>

        <br />
        <button type="submit">Create Record</button>
      </form>
    </div>
  );
}

export default CreateRecord;