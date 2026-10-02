def test_add_list_remove_favourites(signed_in):
    assert signed_in.get("/api/favourites").json() == {"favourites": []}
    r = signed_in.put("/api/favourites/XAU_USD")
    assert [f["code"] for f in r.json()["favourites"]] == ["XAU_USD"]
    signed_in.put("/api/favourites/TSCO.LON")
    signed_in.put("/api/favourites/XAU_USD")  # adding twice is harmless
    codes = [f["code"] for f in signed_in.get("/api/favourites").json()["favourites"]]
    assert codes == ["XAU_USD", "TSCO.LON"]
    r = signed_in.delete("/api/favourites/XAU_USD")
    assert [f["code"] for f in r.json()["favourites"]] == ["TSCO.LON"]


def test_unknown_market_cannot_be_favourited(signed_in):
    assert signed_in.put("/api/favourites/NOPE_NOPE").status_code == 404
    assert signed_in.put("/api/favourites/bad%20code").status_code == 422


def test_favourites_need_sign_in_and_page_header(client, signed_in):
    r = signed_in.put("/api/favourites/EUR_USD", headers={"X-Requested-With": ""})
    assert r.status_code == 403
    signed_in.post("/api/auth/logout")
    assert signed_in.get("/api/favourites").status_code == 401
