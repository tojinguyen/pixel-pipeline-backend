from rembg import new_session


def init_rembg_session(model_name: str = "u2net"):
    """
    Initialize and return a rembg session.
    The caller is responsible for storing the returned session (e.g., in app.state).
    """
    return new_session(model_name)
