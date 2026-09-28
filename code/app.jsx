import React, { useEffect, useState } from "react";
import { Routes, Route, useNavigate } from "react-router-dom";

import Home from "./pages/Home.jsx";
import CreateUser from "./pages/CreateRecord.jsx";
import UpdateUser from "./pages/UpdateRecord.jsx";
import DeleteUser from "./pages/DeleteRecord.jsx";


const API_BASE = "http://localhost:8000";

//important functions to get the user information in order to modify them (create, update or delete)
async function fetchUsers() {
  const res = await fetch(`${API_BASE}/records`, { credentials: "include" });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) throw new Error("Failed to fetch records");
  const data = await res.json();
  return data.records;
}

async function createUser(newUser) {
  const res = await fetch(`${API_BASE}/records`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(newUser),
  });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) throw new Error("Failed to create record");
  const data = await res.json();
  return data;
}

async function updateUser(id, updatedUser) {
  const res = await fetch(`${API_BASE}/records/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(updatedUser),
  });
  if (res.status === 401) throw new Error("Unauthorized");
  if (!res.ok) throw new Error("Failed to update record");
  return { id, ...updatedUser };
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

//
function Navbar({ auth }) {
  return (
    <nav style={{ display: "flex", gap: "15px", marginBottom: "20px" }}>
      <Link to="/">Home</Link>
      {auth.loggedIn && <Link to="/create">Add Record</Link>}
    </nav>
  );
}

function RequireAuth({ auth, children }) {
  if (!auth.loggedIn) {
    return (
      <div>
        <div className="card-header">
          <div className="page-title">Please login</div>
        </div>
        <div className="card-body">
          <div className="notice">Please login to access this page.</div>
        </div>
      </div>
    );
  }
  return children;
}

//
export default function App() {
  const navigate = useNavigate();

  //set up for session authentication
  const [auth, setAuth] = useState({ loggedIn: false, userId: null });

  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(false);

  //get user records if user successfully logs in
  useEffect(() => {
    (async () => {
      if (!auth.loggedIn) {
        setUsers([]);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const data = await fetchUsers();
        setUsers(data);
      } catch (e) {
        console.error("fetchUsers failed:", e);
        if (e.message === "Unauthorized") {
          setAuth({ loggedIn: false, userId: null });
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [auth.loggedIn]);

  //create user record info
  async function onAdd(newUser) {
    try {
      const created = await createUser(newUser);
      setUsers((prev) => [...prev, created]);
      navigate("/");
    } catch (e) {
      console.error("Create failed:", e);
      if (e.message === "Unauthorized") {
        setAuth({ loggedIn: false, userId: null });
      }
    }
  }

  //update user record info
  async function onUpdate(id, updatedUser) {
    try {
      const updated = await updateUser(id, updatedUser);
      setUsers((prev) => prev.map((u) => (u.id === id ? updated : u)));
      navigate("/");
    } catch (e) {
      console.error("Update failed:", e);
      if (e.message === "Unauthorized") {
        setAuth({ loggedIn: false, userId: null });
      }
    }
  }

  //delete user record info
  async function onDelete(id) {
    try {
      await deleteUser(id);
      setUsers((prev) => prev.filter((u) => u.id !== id));
      navigate("/");
    } catch (e) {
      console.error("Delete failed:", e);
      if (e.message === "Unauthorized") {
        setAuth({ loggedIn: false, userId: null });
      }
    }
  }

  return (
    <div className="container">
      <Routes>
        <Route
          path="/"
          element={<Home users={users} loading={loading} auth={auth} />}
        />
        <Route
          path="/create"
          element={
            <RequireAuth auth={auth}>
              <CreateUser onAdd={onAdd} auth={auth} />
            </RequireAuth>
          }
        />
        <Route
          path="/update/:id"
          element={
            <RequireAuth auth={auth}>
              <UpdateUser onUpdate={onUpdate} auth={auth} />
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