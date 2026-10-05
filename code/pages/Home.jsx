import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

const API_BASE = "http://localhost:8439";

function Home({
  users = [],
  records = [],
  relatedEntities = [],
  loading = false,
  auth = { loggedIn: false },
  onDeleteRelatedEntity,
}) {
  const navigate = useNavigate();

  const displayRecords = users.length > 0 ? users : records;

  const [selectedEntityId, setSelectedEntityId] = useState("");
  const [filteredRecords, setFilteredRecords] = useState(null);
  const [filterLoading, setFilterLoading] = useState(false);

  const handleFilterByRelatedEntity = async (entityId) => {
    setSelectedEntityId(entityId);
    if (!entityId) {
      setFilteredRecords(null);
      return;
    }

    try {
      setFilterLoading(true);
      const res = await fetch(
        `${API_BASE}/related-entities/${entityId}/records`,
        { credentials: "include" }
      );
      if (!res.ok) throw new Error("Failed to load records for selected entity");
      const data = await res.json();
      setFilteredRecords(data);
    } catch (err) {
      console.error(err);
      alert(err.message);
    } finally {
      setFilterLoading(false);
    }
  };

  if (loading) return <div>Loading records...</div>;

  const recordsToRender = filteredRecords !== null ? filteredRecords : displayRecords;

  return (
    <div style={{ padding: "20px" }}>
      <h1>Grocery Recall & Product Domain Records</h1>
      <section
        style={{
          marginBottom: "30px",
          padding: "15px",
          border: "1px solid #ccc",
          borderRadius: "8px",
        }}
      >
        <h2>Related Entities (Categories / Authors)</h2>
        {relatedEntities.length === 0 ? (
          <p>No related entities found.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Primary Text</th>
                <th>Secondary Text</th>
                <th>Code</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {relatedEntities.map((entity) => (
                <tr key={entity.id}>
                  <td>{entity.id}</td>
                  <td>{entity.primary_text}</td>
                  <td>{entity.secondary_text}</td>
                  <td><code>{entity.code}</code></td>
                  <td>
                    {onDeleteRelatedEntity && (
                      <button
                        onClick={() => onDeleteRelatedEntity(entity.id)}
                        style={{ color: "red", cursor: "pointer" }}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section style={{ marginBottom: "20px" }}>
        <label htmlFor="relationship-filter">
          <strong>Filter Primary Records by Related Entity: </strong>
        </label>
        <select
          id="relationship-filter"
          value={selectedEntityId}
          onChange={(e) => handleFilterByRelatedEntity(e.target.value)}
        >
          <option value="">-- Show All Records --</option>
          {relatedEntities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.primary_text} ({e.code})
            </option>
          ))}
        </select>
        {filterLoading && <span style={{ marginLeft: "10px" }}>Filtering...</span>}
      </section>

      <section>
        <h2>Primary Domain Records</h2>
        {recordsToRender.length === 0 ? (
          <p>No primary records found.</p>
        ) : (
          <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #333" }}>
                <th>ID</th>
                <th>Primary Field</th>
                <th>Secondary Field</th>
                <th>Unique Code</th>
                <th>Quantity</th>
                <th>Related Entity ID</th>
                {auth.loggedIn && <th>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {recordsToRender.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td>
                  <td>{item.name || item.primary_field}</td>
                  <td>{item.description || item.secondary_field}</td>
                  <td><code>{item.unique_code}</code></td>
                  <td>{item.quantity}</td>
                  <td>{item.related_entity_id}</td>
                  {auth.loggedIn && (
                    <td>
                      <Link to={`/update/${item.id}`} state={{ record: item }}>Update</Link>
                      <Link to={`/delete/${item.id}`} state={{ record: item.id }}>Delete</Link>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default Home;