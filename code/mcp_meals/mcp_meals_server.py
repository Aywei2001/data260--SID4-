from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("meals")

get_db = "https://www.themealdb.com/api/json/v1/1"

@mcp.tool()
async def search_meals_by_name(query: str, limit: int = 5) -> list | str:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{get_db}/search.php", params={"s": query})
        data = response.json()

        if not data.get("meals"):
            return "No matches found."

        results = []

        for meal in data["meals"][:limit]:
            results.append({"id": meal.get("idMeal"), "name": meal.get("strMeal"), "area": meal.get("strArea"), 
                            "category": meal.get("strCategory"), "thumb": meal.get("strMealThumb")})

        return results

@mcp.tool()
async def meals_by_ingredient(ingredient: str, limit: int = 12) -> list | str:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{get_db}/filter.php", params={"i": ingredient})
        data = response.json()

        if not data.get("meals"):
            return "No matches found."

        results = []
        
        for meal in data["meals"][:limit]:
            results.append({"id": meal.get("idMeal"), "name": meal.get("strMeal"), "thumb": meal.get("strMealThumb")})

        return results

def format_full_meal(meal: dict) -> dict:

    ingredients = []

    for i in range(1,21):
        ingrts = meal.get(f"strIngredient{i}")
        meals = meal.get(f"strMeasure{i}")

        if ingrts and ingrts.strip():
            ingredients.append({"name": ingrts.strip(), "measure": meals.strip() if meals else ""})

    return {"id": meal.get("idMeal"), "name": meal.get("strMeal"), "category": meal.get("strCategory"), "area": meal.get("strArea"),"instructions": meal.get("strInstructions"), 
            "image": meal.get("strMealThumb"), "source": meal.get("strSource"),"youtube": meal.get("strYoutube"), "ingredients": ingredients}


@mcp.tool()
async def meal_details(id: str) -> dict | str:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{get_db}/lookup.php", params={"i": id})
        data = response.json()

        if not data.get("meals"):
            return "No matches found."

        return format_full_meal(data["meals"][0])
        

@mcp.tool()
async def random_meal() -> dict | str:
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{get_db}/random.php")
        data = response.json()

        if not data.get("meals"):
            return "No matches found."

        return format_full_meal(data["meals"][0])


if __name__ == "__main__":
    mcp.run()