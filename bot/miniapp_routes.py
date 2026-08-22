from aiohttp import web


def register_miniapp_routes(app: web.Application, api) -> None:
    """The public Mini App API, grouped by product area for easy extension."""
    app.add_routes([
        web.get("/", api.index),
        web.get("/assets/{name}", api.asset),
        web.get("/api/bootstrap", api.bootstrap),
    ])
    app.add_routes([
        web.post("/api/company", api.create_company),
        web.post("/api/company/switch", api.switch_company),
        web.post("/api/company/leave", api.leave_company),
    ])
    app.add_routes([
        web.post("/api/ideas", api.add_idea),
        web.put("/api/ideas/{idea_id}", api.update_idea),
        web.delete("/api/ideas/{idea_id}", api.delete_idea),
        web.post("/api/ideas/{idea_id}/comments", api.add_comment),
        web.post("/api/ideas/{idea_id}/reactions", api.react),
    ])
    app.add_routes([
        web.post("/api/vote/start", api.start_vote),
        web.post("/api/vote/cast", api.cast_vote),
        web.post("/api/vote/close", api.close_vote),
        web.post("/api/plan", api.plan),
        web.post("/api/date/options", api.add_date_option),
        web.post("/api/date/vote", api.vote_date),
        web.post("/api/date/confirm", api.confirm_date),
    ])
    app.add_routes([
        web.put("/api/activity/{activity_id}", api.reschedule_activity),
        web.post("/api/activity/{activity_id}/confirm", api.confirm_activity),
        web.post("/api/activity/{activity_id}/photo", api.upload_activity_photo),
        web.get("/api/archive/photo/{photo_id}", api.archive_photo),
        web.post("/api/settings", api.update_settings),
    ])
