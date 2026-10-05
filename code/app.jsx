import React, { useEffect, useState } from "react";
import { Routes, Route, useNavigate, Link } from "react-router-dom";

import Home from "./pages/Home.jsx";
import CreateUser from "./pages/CreateRecord.jsx";
import UpdateUser from "./pages/UpdateRecord.jsx";
import DeleteUser from "./pages/DeleteRecord.jsx";
import Login from "./pages/login.jsx";

const API_BASE = "http://localhost:8439";

async function fetchUsers(skip = 0, limit = 10) {
  const res = await fetch(`${API_BASE}/records?skip=${skip}&limit=${limit}`, { credentials: "include" });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) throw new Error("Failed to fetch records");
  return await res.json();
}

async function createUser(newUser) {
  const res = await fetch(`${API_BASE}/records`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(newUser),
  });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to create record");
  }
  return await res.json();
}

async function updateUser(id, updatedUser) {
  const res = await fetch(`${API_BASE}/records/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(updatedUser),
  });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to update record");
  }
  return await res.json();
}

async function deleteUser(id) {
  const res = await fetch(`${API_BASE}/records/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) throw new Error("Failed to delete record");
  return id;
}

async function fetchRelatedEntities(skip = 0, limit = 10) {
  const res = await fetch(`${API_BASE}/related-entities?skip=${skip}&limit=${limit}`, { credentials: "include" });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) throw new Error("Failed to fetch related entities");
  return await res.json();
}

async function createRelatedEntity(entity) {
  const res = await fetch(`${API_BASE}/related-entities`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(entity),
  });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Failed to create related entity");
  }
  return await res.json();
}

async function deleteRelatedEntity(id) {
  const res = await fetch(`${API_BASE}/related-entities/${id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || "Cannot delete related entity with existing primary records");
  }
  return id;
}

function Navbar({ auth, setAuth }) {
  const navigate = useNavigate();

  const handleLogout = async () => {
    try {
      await fetch(`${API_BASE}/logout`, { method: "POST", credentials: "include" });
    } catch (e) {
      console.error("Logout request failed:", e);
    } finally {
      setAuth({ loggedIn: false, userId: null });
      navigate("/login");
    }
  };

  return (
    <nav style={{ display: "flex", gap: "15px", marginBottom: "20px", alignItems: "center" }}>
      <Link to="/">Home</Link>
      {auth.loggedIn && <Link to="/create">Add Record</Link>}
      {auth.loggedIn ? (
        <button onClick={handleLogout} style={{ marginLeft: "auto", cursor: "pointer" }}>
          Logout
        </button>
      ) : (
        <Link to="/login" style={{ marginLeft: "auto" }}>Login</Link>
      )}
    </nav>
  );
}

function RequireAuth({ auth, children }) {
  if (!auth.loggedIn) {
    return (
      <div style={{ padding: "20px" }}>
        <div className="card-header">
          <div className="page-title">Please login</div>
        </div>
        <div className="card-body">
          <div className="notice">Please <Link to="/login">login</Link> to access this page.</div>
        </div>
      </div>
    );
  }
  return children;
}

export default function App() {
  const navigate = useNavigate();

  const [auth, setAuth] = useState({ loggedIn: false, userId: null });
  const [users, setUsers] = useState([]);
  const [relatedEntities, setRelatedEntities] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      if (!auth.loggedIn) {
        setUsers([]);
        setRelatedEntities([]);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const [recordsData, entitiesData] = await Promise.all([
          fetchUsers(),
          fetchRelatedEntities(),
        ]);
        setUsers(recordsData);
        setRelatedEntities(entitiesData);
      } catch (e) {
        console.error("Data fetching failed:", e);
        if (e.message === "Unauthorized") {
          setAuth({ loggedIn: false, userId: null });
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [auth.loggedIn]);

  async function onAdd(newUser) {
    try {
      const created = await createUser(newUser);
      setUsers((prev) => [...prev, created]);
      navigate("/");
    } catch (e) {
      console.error("Create failed:", e);
      alert(e.message);
      if (e.message === "Unauthorized") {
        setAuth({ loggedIn: false, userId: null });
      }
    }
  }

  async function onUpdate(id, updatedUser) {
    try {
      const updated = await updateUser(id, updatedUser);
      setUsers((prev) => prev.map((u) => (u.id === id ? updated : u)));
      navigate("/");
    } catch (e) {
      console.error("Update failed:", e);
      alert(e.message);
      if (e.message === "Unauthorized") {
        setAuth({ loggedIn: false, userId: null });
      }
    }
  }

  async function onDelete(id) {
    try {
      await deleteUser(id);
      setUsers((prev) => prev.filter((u) => u.id !== id));
      navigate("/");
    } catch (e) {
      console.error("Delete failed:", e);
      alert(e.message);
      if (e.message === "Unauthorized") {
        setAuth({ loggedIn: false, userId: null });
      }
    }
  }

  async function onAddRelatedEntity(newEntity) {
    try {
      const created = await createRelatedEntity(newEntity);
      setRelatedEntities((prev) => [...prev, created]);
    } catch (e) {
      console.error("Create related entity failed:", e);
      alert(e.message);
    }
  }

  async function onDeleteRelatedEntity(id) {
    try {
      await deleteRelatedEntity(id);
      setRelatedEntities((prev) => prev.filter((e) => e.id !== id));
    } catch (e) {
      console.error("Delete related entity failed:", e);
      alert(e.message);
    }
  }

  return (
    <div className="container" style={{ maxWidth: "800px", margin: "0 auto" }}>
      <Navbar auth={auth} setAuth={setAuth} />
      <Routes>
        <Route
          path="/login"
          element={<Login setAuth={setAuth} />}
        />
        <Route
          path="/"
          element={
            <Home
              users={users}
              relatedEntities={relatedEntities}
              loading={loading}
              auth={auth}
              onDeleteRelatedEntity={onDeleteRelatedEntity}
            />
          }
        />
        <Route
          path="/create"
          element={
            <RequireAuth auth={auth}>
              <CreateUser
                onAdd={onAdd}
                relatedEntities={relatedEntities}
                onAddRelatedEntity={onAddRelatedEntity}
                auth={auth}
              />
            </RequireAuth>
          }
        />
        <Route
          path="/update/:id"
          element={
            <RequireAuth auth={auth}>
              <UpdateUser
                onUpdate={onUpdate}
                relatedEntities={relatedEntities}
                records={users}
                auth={auth}
              />
            </RequireAuth>
          }
        />
        <Route
          path="/delete/:id"
          element={
            <RequireAuth auth={auth}>
              <DeleteUser onDelete={onDelete} auth={auth} />
            </RequireAuth>
          }
        />
      </Routes>
    </div>
  );
}