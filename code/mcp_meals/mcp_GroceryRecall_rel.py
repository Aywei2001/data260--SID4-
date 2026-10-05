from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("GroceryRecall_rel")

# OpenFDA Food Enforcement API base endpoint
get_db = "https://api.fda.gov/food/enforcement.json"

def create_envelope(data = None, error = None) -> dict:
    if error:
        return {"ok": False, "data": None, "error": error}
    
    return {"ok": True, "data": data, "error": None}

@mcp.tool()
async def search_grocery_recalls(query: str) -> dict:
    try:
        if not query or not query.strip():
            return create_envelope(error = "Please enter a product or brand name to search recalls!")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{get_db}?search=product_description:{query}&limit=5")
            
            if response.status_code == 404:
                return create_envelope(error = "No matching grocery recalls found! Try again.")
                
            res_json = response.json()
            results = res_json.get("results", [])

            if not results:
                return create_envelope(error = "No matching grocery recalls found! Try again.")
        
            recall_matches = [{
                "recall_number": r.get("recall_number"), 
                "product_description": r.get("product_description"), 
                "reason_for_recall": r.get("reason_for_recall"),
                "company_name": r.get("recalling_firm"), 
                "recall_date": r.get("report_date")
            } for r in results]

        return create_envelope(data = recall_matches)
        
    except Exception as e:
        return create_envelope(error = f"Error fetching data: {str(e)}")

@mcp.tool()
async def recall_detail_lookup(recall_number: str) -> dict:
    try:
        if not recall_number or not recall_number.strip():
            return create_envelope(error = "Please enter a recall number to continue!")
        
        async with httpx.AsyncClient() as client:
            #search by a recall number
            response = await client.get(f"{get_db}?search=recall_number:{recall_number}")

            if response.status_code == 404:
                return create_envelope(error = "Could not find any information on this recall number.")

            res_json = response.json()
            results = res_json.get("results", [])

            if not results:
                return create_envelope(error = "Could not find any information on this recall number.")

            data = results[0]
            recall_details = {
                "recall_number": data.get("recall_number"),
                "product_description": data.get("product_description"),
                "reason_for_recall": data.get("reason_for_recall"),
                "company_name": data.get("recalling_firm"),
                "distribution_pattern": data.get("distribution_pattern"),
                "recall_date": data.get("report_date"),
                "status": data.get("status")
            }

            return create_envelope(data = recall_details)

    except Exception as e:
        return create_envelope(error = str(e))


@mcp.tool()
async def aggregate_company_stats(company_name: str) -> dict:
    try:
        if not company_name or not company_name.strip():
            return create_envelope(error = "Please enter a company name to continue!")
        
        async with httpx.AsyncClient() as client:
            #search OpenFDA by recalling firm name
            response = await client.get(f"{get_db}?search=recalling_firm:{company_name}&limit=100")
            
            if response.status_code == 404:
                return create_envelope(error = "Could not find any recall data for this company.")

            res_json = response.json()
            company_info = res_json.get("results", [])

            if not company_info:
                return create_envelope(error = "Could not find any recall data for this company.")

            total_recalls = len(company_info)
            product_list = [r.get("product_description")[:50] + "..." for r in company_info if r.get("product_description")]

            company_summary = {
                "company_name": company_name, 
                "total_recalls_recorded": total_recalls,
                "recent_products_recalled": product_list[:5]
            }

            return create_envelope(data = company_summary)
    
    except Exception as e:
        return create_envelope(error = str(e))


if __name__ == "__main__":
    mcp.run()