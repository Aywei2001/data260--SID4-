import React, { useState, useEffect } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";

function UpdateRecord({ onUpdate, onUpdateRecord, relatedEntities = [], records = [] }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { id: paramId } = useParams(); 
  const handleUpdateFunc = onUpdate || onUpdateRecord;

  const initialRecord =
    location.state?.record ||
    records.find((r) => String(r.id) === String(paramId)) ||
    {};

  const [id, setId] = useState(paramId || initialRecord.id || "");
  const [name, setName] = useState(initialRecord.name || "");
  const [description, setDescription] = useState(
    initialRecord.description || initialRecord.desc || ""
  );
  const [uniqueCode, setUniqueCode] = useState(initialRecord.unique_code || "");
  const [quantity, setQuantity] = useState(initialRecord.quantity || 10);
  const [relatedEntityId, setRelatedEntityId] = useState(
    initialRecord.related_entity_id ||
      (relatedEntities.length > 0 ? relatedEntities[0].id : "")
  );

  const [error, setError] = useState("");

  useEffect(() => {
    if (initialRecord.id) {
      setId(initialRecord.id);
      setName(initialRecord.name || "");
      setDescription(initialRecord.description || initialRecord.desc || "");
      setUniqueCode(initialRecord.unique_code || "");
      setQuantity(initialRecord.quantity || 10);
      setRelatedEntityId(
        initialRecord.related_entity_id ||
          (relatedEntities.length > 0 ? relatedEntities[0].id : "")
      );
    }
  }, [initialRecord, relatedEntities]);

  const handleSubmit = async (e) => {
    e.preventDefault(); 
    setError("");

    if (!id) {
      setError("Please specify a valid Record ID to update.");
      return;
    }

    const updateData = {
      id: Number(id),
      name,
      description,
      unique_code: uniqueCode,
      quantity: Number(quantity),
      related_entity_id: Number(relatedEntityId),
    };

    try {
      if (handleUpdateFunc) {
        await handleUpdateFunc(updateData);
      } else {

        const response = await fetch(`http://localhost:8439/records/${id}`, {
          method: "PUT", 
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify(updateData),
        });

        if (response.status === 401) {
          throw new Error("Log in Required");
        }

        if (!response.ok) {
          const errBody = await response.json().catch(() => ({}));
          throw new Error(errBody.detail || "Unable to update record");
        }

        navigate("/");
      }
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h2>Update Record</h2>
      
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="record-id">Record ID: </label>
          <input
            id="record-id"
            type="number"
            value={id}
            onChange={(e) => setId(e.target.value)}
            required
            disabled={!!paramId} 
          />
        </div>
        <div>
          <label htmlFor="update-name">Primary Field (Name): </label>
          <input
            id="update-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="update-description">Secondary Field (Description): </label>
          <input
            id="update-description"
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="update-code">Unique Code: </label>
          <input
            id="update-code"
            type="text"
            value={uniqueCode}
            onChange={(e) => setUniqueCode(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="update-quantity">Quantity: </label>
          <input
            id="update-quantity"
            type="number"
            min="0"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            required
          />
        </div>

        <div>
          <label htmlFor="update-related-entity">Related Entity: </label>
          <select
            id="update-related-entity"
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
        <button type="submit">Confirm Record Update</button>
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

export default UpdateRecord;